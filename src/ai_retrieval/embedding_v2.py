"""descriptive.embedding.v2 -- a market-state vector the system can actually see.

REFINE-DESCRIPTIVE-MEMORY-VECTOR-V2 (2026-08-06).

v1 reused the legacy 47-dimension encoder. The read-only review of the ten
proposed August 6 records proved it could not represent this system's own
vocabulary:

  * `delivery_direction` was routed through `_norm_dir()`, which matches
    bullish/bearish/conflicted/neutral prefixes. Every real ICT delivery state
    (`accumulation_building`, `mixed`, `full_distribution_alignment`,
    `manipulation_to_distribution`) fell through to `none`, so ONE dimension was
    on in all ten records and in five of six queries. It contributed no
    discrimination and added +0.05..0.07 similarity to every pair -- enough to
    lift one query's only "match" from 0.4629 to 0.5345 and over the floor.
  * `structure_state` and `liquidity_state` were not represented at all.
  * the two confidence scalars were hardcoded `None` on the memory path.
  * the exhaustion scalar was never populated.
  * records #4/#5/#6 had byte-identical vectors; #5 differed in delivery and
    structure, and the vector could not see either.

The legacy vocabularies were also incomplete against their own producers:
`volatility_classifier` emits `expanding` (3 August 6 scans) and
`session_engine` emits `power_hour`; neither appears in the v1 lists, so both
silently encoded as all-zeros.

v2 takes its vocabulary from the producers, not from one session's observations,
and states the whole layout in ONE manifest that writer and reader share.

MISSING IS NOT A FEATURE. An unknown or unsupported categorical value produces
all zeros for its group and a validation note. Two incomplete records must never
resemble each other *because* they are incomplete -- that is the v1 defect with
a different name.
"""
from __future__ import annotations

import copy
import hashlib
import json

import numpy as np

_SQRT2 = 2.0 ** 0.5

#: v2.2 (2026-08-07): the delivery vocabulary gained `bearish_delivery` and
#: `bullish_delivery`, which the authoritative producer emits and v2.1 omitted.
#: That is a GEOMETRY change (55 -> 57 dimensions), so the version moves. The
#: ten August 6 records were authored under v2.1 and the reader will refuse
#: them as `embedding_manifest_mismatch` until they are re-authored from the
#: immutable archive -- failing closed, which is correct: a corpus must never be
#: read in a space it was not written in.
EMBEDDING_VERSION = "descriptive.embedding.v2.2"

# ── authoritative vocabularies ───────────────────────────────────────────────
# Each list is copied from the module that PRODUCES the value, and each entry
# below names that module. `unknown` is deliberately absent from every list:
# it is the all-zeros case, not a category.

#: src/regime_classification/regime_classifier.py::_FAMILIES (minus "unknown")
REGIMES = ("trend_up", "trend_down", "range_rotation", "chop", "expansion_up",
           "expansion_down", "reversal_attempt", "high_volatility",
           "low_volatility")

#: src/volatility/volatility_classifier.py::_state -- every reachable return.
#: v1 omitted "expanding", which August 6 emitted 3 times.
VOLATILITY = ("liquidity_vacuum", "toxic", "unstable", "explosive", "expanding",
              "stable")

#: src/market_data/session_engine.py::_SESSIONS. v1 omitted "power_hour".
#: "closed" is the out-of-band fallback and encodes as all zeros.
SESSION_PHASES = ("premarket", "ny_open", "morning_continuation", "lunch",
                  "afternoon", "power_hour", "after_hours")

#: src/ai_brain/brain_validation.py::VALID_PHASES
NARRATIVE_PHASES = ("accumulation", "manipulation", "distribution", "reversal",
                    "continuation", "exhaustion", "transition", "neutral",
                    "conflicted")

#: src/ai_brain/brain_validation.py::VALID_DIRECTIONS -- as a DISTRIBUTION,
#: not a one-hot. See `direction_block`.
DIRECTIONS = ("bullish", "bearish", "conflicted", "neutral")

#: src/structure/po3_engine.py::_po3_alignment -- every reachable return.
#: This is the block v1 could not see.
#: PROD-20260807 DEFECT: this list was derived from `po3_engine._po3_alignment`,
#: but the field retrieval actually reads is
#: `shared_market_context.delivery_state`, which ALSO emits directional values.
#: 30 of 171 live scans carried `bearish_delivery`/`bullish_delivery`, matched
#: nothing, and refused the whole query as missing a mandatory block.
#: THE AUTHORITATIVE PRODUCER is `shared_market_context._delivery`, not
#: `po3_engine._po3_alignment`. It returns:
#:
#:     state = f"{direction}_delivery" if direction else po3_align
#:
#: so `bearish_delivery` / `bullish_delivery` are NOT aliases of the alignment
#: states -- they are emitted when an alignment exists AND a distribution or
#: manipulation direction resolves, and the alignment is DISCARDED when they
#: fire. They carry directional information the five alignment states cannot.
#: `insufficient_delivery_evidence` is a third reachable state: a deliberate
#: refusal to synthesise delivery from structure bias. It is a real state, not
#: an unknown, so it is a category. Only `unknown` is the all-zeros case.
DELIVERY_STATES = ("full_distribution_alignment", "manipulation_to_distribution",
                   "accumulation_building", "no_clear_alignment", "mixed",
                   "bullish_delivery", "bearish_delivery",
                   "insufficient_delivery_evidence")

#: Derived deterministically from the authoritative liquidity block
#: (`nearest_buy_side` / `nearest_sell_side`). v1 collapsed one-sided pools into
#: a single token that could not distinguish which side was missing.
LIQUIDITY_STATES = ("two_sided_pools", "buy_side_only", "sell_side_only",
                    "no_pools")

#: STRUCTURE_WITNESS carries one bos_event/mss_event flag per timeframe, over
#: exactly four timeframes, so counts are structurally bounded at 4.
STRUCTURE_EVENT_CAP = 4

#: Confidence is a 0-100 integer (brain_schema `phase_confidence`). A value
#: outside the range is REJECTED, not clipped -- a 140 is a defect, and
#: silently flattening it to 100 destroys the evidence that it happened.
CONFIDENCE_MIN, CONFIDENCE_MAX = 0.0, 100.0



# ── semantic authority tiers ─────────────────────────────────────────────────
# REFINE-DESCRIPTIVE-MEMORY-BLOCK-WEIGHTING (2026-08-06).
#
# v2 gave all 13 blocks weight 1.0. The contribution audit showed why that
# fails: in a one-hot block a CONTRADICTION contributes 0 to the cosine
# numerator, it does not subtract. So agreement on many secondary blocks
# accumulates while disagreement on the load-bearing ones costs nothing. The
# bullish-expansion query scored 0.5374 against segment #1 with session phase,
# delivery, liquidity, active draw and exhaustion each supplying 17.2% of the
# numerator, while market regime, direction and narrative phase -- all three
# contradicting -- supplied exactly 0.
#
# Weights enter the cosine numerator as w^2 (both q and r coordinates are
# scaled), and also enter both denominators as w^2. Raising a load-bearing
# weight therefore RAISES THE DENOMINATOR of a contradictory pair without
# raising its numerator, while an agreeing pair scales numerator and denominator
# together. That is the lever: it penalises contradiction without inventing
# negative similarity.
#
# The tiers below are derived from production doctrine, NOT from desired August 6
# outputs. Two amendments were made to the tiering proposed in the mission, each
# with a citation:
#
#   STRUCTURE DEMOTED to contextual. src/ai_brain/brain_prompt.py, STRUCTURE
#   SAFETY CONTRACT points 1-6 and "STRUCTURE is a WITNESS, not the authority.
#   It lags; it counts liquidity raids as strength. Weigh it last." Treating
#   structure as load-bearing would contradict the system's own mandatory
#   contract.
#
#   PROTECTED SWINGS and ACTIVE DRAW PROMOTED to load-bearing. Same file:
#   "DELIVERY, LIQUIDITY, and PROTECTED SWINGS are load-bearing", and "Direction
#   MUST come from delivery, liquidity, protected swings, active draw, and clean
#   narrative evidence -- never from structure."

#: The principal market condition. Contradiction here is a real disagreement.
LOAD_BEARING_BLOCKS = ("market_regime", "volatility_state",
                       "direction_distribution", "delivery_state",
                       "liquidity_state", "active_draw",
                       "protected_high", "protected_low")

#: Refines the condition. Must not overturn contradictions in load-bearing state.
CONTEXTUAL_BLOCKS = ("session_phase", "narrative_phase", "structure_evidence",
                     "exhaustion")

#: How strongly the prior system expressed an observation -- never whether the
#: observation was correct. It may order near-ties; it may not create a match.
DIAGNOSTIC_BLOCKS = ("confidence",)

#: Named, auditable profiles. Values come from a small rational set.
WEIGHT_PROFILES = {
    "EQUAL_V2":            {"load": 1.00, "context": 1.00, "diagnostic": 1.00},
    "MINIMAL_CHANGE":      {"load": 1.00, "context": 0.75, "diagnostic": 0.50},
    "AUTHORITY_TIERED_A":  {"load": 1.25, "context": 0.75, "diagnostic": 0.50},
    "AUTHORITY_TIERED_B":  {"load": 1.50, "context": 0.75, "diagnostic": 0.50},
}

ACTIVE_PROFILE = "AUTHORITY_TIERED_A"


def block_weights(profile: str = None) -> dict:
    """Resolved per-block weight map for a named profile."""
    tiers = WEIGHT_PROFILES[profile or ACTIVE_PROFILE]
    out = {}
    for name in LOAD_BEARING_BLOCKS:
        out[name] = tiers["load"]
    for name in CONTEXTUAL_BLOCKS:
        out[name] = tiers["context"]
    for name in DIAGNOSTIC_BLOCKS:
        out[name] = tiers["diagnostic"]
    return out


# ── query completeness law ───────────────────────────────────────────────────
#: A production query must state these. Omitting one does not make a record
#: "more similar" -- it makes the question unanswerable. Without this rule an
#: underspecified query scores HIGHER, because an unsupplied block shrinks |q|
#: while contributing nothing to either side: exactly the effect that moved the
#: bullish-expansion score between 0.465 and 0.587 depending on how much of the
#: state the query bothered to state.
MANDATORY_QUERY_BLOCKS = ("market_regime", "volatility_state",
                          "direction_distribution", "delivery_state",
                          "liquidity_state")


class EmbeddingError(ValueError):
    """The record cannot be embedded as written. Never guessed around."""


# ── the manifest ─────────────────────────────────────────────────────────────
def _build_manifest() -> dict:
    groups, index = [], 0

    def block(name, categories=None, size=None, kind="one_hot", note=""):
        nonlocal index
        n = len(categories) if categories is not None else size
        groups.append({"name": name, "kind": kind, "start": index,
                       "end": index + n, "size": n,
                       "categories": list(categories) if categories else None,
                       "note": note})
        index += n

    block("market_regime", REGIMES,
          note="unknown -> all zeros")
    block("volatility_state", VOLATILITY,
          note="unknown -> all zeros")
    block("session_phase", SESSION_PHASES,
          note="closed/unknown -> all zeros")
    block("narrative_phase", NARRATIVE_PHASES,
          note="unknown -> all zeros")
    block("direction_distribution", DIRECTIONS, kind="distribution",
          note="proportions over eligible scans, then L2-normalised")
    block("delivery_state", DELIVERY_STATES,
          note="its own vocabulary; NEVER routed through _norm_dir")
    block("structure_evidence", size=3, kind="numeric",
          note="[bos_count/4, mss_count/4, quiet_flag]")
    block("liquidity_state", LIQUIDITY_STATES,
          note="derived from nearest_buy_side / nearest_sell_side presence")
    block("active_draw", size=2, kind="two_state",
          note="[present, absent] -- absence of a draw is a market FACT; "
               "unknown is both zero")
    block("protected_high", size=1, kind="presence",
          note="presence only; the price level never enters similarity")
    block("protected_low", size=1, kind="presence",
          note="presence only; the price level never enters similarity")
    block("exhaustion", size=2, kind="two_state",
          note="shared_market_context._exhaustion_present -- an INDEPENDENT "
               "measurement, not a restatement of narrative_phase:exhaustion "
               "(79 true / 93 false on August 6, while the phase read "
               "exhaustion only 23 times). unknown is both zero.")
    block("confidence", size=2, kind="numeric",
          note="[mean/100, (max-min)/100]")

    return {
        "embedding_version": EMBEDDING_VERSION,
        "dimensions": index,
        "groups": groups,
        "missing_value_law": (
            "An unknown or unsupported categorical value contributes ALL ZEROS "
            "for its group plus a validation note. No shared 'none' or "
            "'unknown' dimension exists anywhere in this vector."),
        "normalization_law": (
            "One-hot groups are 0/1. direction_distribution is proportions over "
            "eligible scans, L2-normalised so every record contributes equal "
            "magnitude from direction regardless of how mixed it was. Structure "
            f"counts are divided by {STRUCTURE_EVENT_CAP} (four timeframes, so "
            "the count is structurally bounded) and capped at 1.0. Confidence "
            "is /100; a value outside 0-100 is rejected, never clipped."),
        "structure_event_cap": STRUCTURE_EVENT_CAP,
        "confidence_range": [CONFIDENCE_MIN, CONFIDENCE_MAX],
        # STEP 4B.12 §4 UNIT 3 — v2: STRUCTURE QUIET NOW REQUIRES EVALUABILITY.
        #
        # v1 read `quiet` as "zero positive events". It had no way to ask whether
        # the propositions behind those zeros were EVALUATED, because the witness
        # did not carry evaluability. So a timeframe the engine could not read
        # counted toward a quiet market exactly like one it had read and found
        # still.
        #
        # v2 authors quiet only when the structure propositions are
        # DETECTOR_EVALUATED. That is a different reading of the same evidence,
        # so it is a different PARSER, and the manifest fingerprint moves with it.
        #
        # THIS IS THE DE-AUTHORIZATION MECHANISM, NOT A SIDE EFFECT. Records
        # authored under v1 keep their stored vectors byte-for-byte -- and
        # `_vector_incompatible` refuses to compare them, because their dim-45
        # quiet bit means something the current contract does not endorse. The
        # v1 record remains a true statement about what v1 believed; it is no
        # longer treated as current evidence about the market.
        "parser_versions": {"structure": "structure_witness_v2",
                            "liquidity": "liquidity_pools_v1"},
        # v2.1: resolved from the active semantic-authority profile. Reweighting
        # changes this map, the manifest fingerprint, and therefore every
        # previously issued authorization -- without changing dimensionality.
        "weight_profile": ACTIVE_PROFILE,
        "weight_tiers": dict(WEIGHT_PROFILES[ACTIVE_PROFILE]),
        "block_weights": block_weights(),
        "authority_tiers": {"load_bearing": list(LOAD_BEARING_BLOCKS),
                            "contextual": list(CONTEXTUAL_BLOCKS),
                            "diagnostic": list(DIAGNOSTIC_BLOCKS)},
        "mandatory_query_blocks": list(MANDATORY_QUERY_BLOCKS),
        "internal_normalization_law": (
            "Every block is bounded to a maximum norm of 1.0 BEFORE its weight "
            "is applied, so no block gains authority from dimension count or "
            "from several coordinates being active at once. One-hot, two-state "
            "and presence blocks are already unit-or-zero. direction_distribution "
            "is L2-normalised. structure_evidence is divided by sqrt(2) in the "
            "non-quiet case (its reachable maximum) so intensity is PRESERVED "
            "while the block cannot exceed a categorical one. confidence is "
            "divided by sqrt(2) for the same reason."),
    }


MANIFEST = _build_manifest()
EMBED_DIM_V2 = MANIFEST["dimensions"]
_GROUP = {g["name"]: g for g in MANIFEST["groups"]}


def manifest_fingerprint() -> str:
    blob = json.dumps(MANIFEST, sort_keys=True, separators=(",", ":"))
    return "emb:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def vector_fingerprint(vector) -> str:
    """Identity of a vector's VALUES, rounded so float noise cannot split it."""
    rounded = [round(float(v), 6) for v in vector]
    blob = json.dumps(rounded, separators=(",", ":"))
    return "vec:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ── derivations from authoritative underlying fields ─────────────────────────
def liquidity_state(nearest_buy_side, nearest_sell_side) -> str:
    """The four real pool configurations. v1 could not tell buy-only from
    sell-only, which for a directional system are opposite situations."""
    buy, sell = nearest_buy_side is not None, nearest_sell_side is not None
    if buy and sell:
        return "two_sided_pools"
    if buy:
        return "buy_side_only"
    if sell:
        return "sell_side_only"
    return "no_pools"


def _structure_capability(w: dict, present: list) -> str:
    """Coarse capability across the timeframes that spoke. Weakest link wins.

    Read from the witness rather than re-derived: `brain_input` owns the
    producer-token mapping, and a second mapping here would be a second
    authority for the same epistemic fact.

    A legacy witness predating the evaluation objects yields UNKNOWN, never
    DETECTOR_EVALUATED -- the whole point is that absence may not be promoted to
    evidence. Quiet is a statement about the WHOLE market read, so one
    unevaluable timeframe is enough to withdraw the claim.
    """
    seen = set()
    for tf in present:
        for prop in ("bos_evaluation", "mss_evaluation"):
            ev = (w[tf] or {}).get(prop)
            seen.add(ev.get("capability") if isinstance(ev, dict) else "UNKNOWN")
    if "UNKNOWN" in seen:
        return "UNKNOWN"
    if "UNEVALUABLE_EVIDENCE" in seen:
        return "UNEVALUABLE_EVIDENCE"
    return "DETECTOR_EVALUATED"


def structure_evidence(witness: dict) -> dict:
    """BOS/MSS counts read from STRUCTURE_WITNESS itself.

    v1 built a display string (`witness_bos_3_mss_0`) and then embedded nothing.
    Reading the underlying flags means there is no string to parse and no
    unparseable string to misread as quiet.
    """
    w = witness or {}
    tfs = ("15m", "5m", "3m", "1m")
    present = [tf for tf in tfs if isinstance(w.get(tf), dict)]
    if not present:
        raise EmbeddingError("structure_witness_absent: no timeframe blocks; "
                             "refusing to encode this as 'quiet'")
    bos = sum(1 for tf in present if w[tf].get("bos_event"))
    mss = sum(1 for tf in present if w[tf].get("mss_event"))
    # STEP 4B.12 §4 UNIT 3 — QUIET IS A CLAIM, AND A CLAIM NEEDS AUTHORITY.
    #
    # `quiet = (bos == 0 and mss == 0)` reads zero POSITIVES as proof of a quiet
    # market. After Unit 2 the engine can be certain there was no break, or
    # unable to establish whether there was one, and both published zero here.
    # Measured on 1000 opportunities, 4 carried an unevaluable transition; every
    # one of them was embedded and retrievable as authoritative quiet.
    #
    # v1's own comment says nothing unparseable may be "misread as quiet". This
    # is that same rule applied one layer deeper: silence is evidence only where
    # the detector had an opportunity to speak.
    #
    # NOT substituted with a claim of activity. `quiet=False` with zero counts
    # yields the count branch, whose vector is [0, 0, 0] -- distinct from quiet's
    # [0, 0, 1] and from any real event. The capability says WHY.
    cap = _structure_capability(w, present)
    return {"bos_count": bos, "mss_count": mss,
            "quiet": bool(bos == 0 and mss == 0 and cap == "DETECTOR_EVALUATED"),
            "structure_capability": cap,
            "timeframes_seen": len(present),
            "parser": MANIFEST["parser_versions"]["structure"]}


def direction_proportions(distribution: dict, eligible_scans: int) -> dict:
    """Proportions over eligible scans. Must sum to 1.0 within tolerance.

    A segment that read bearish 8 / conflicted 8 / neutral 6 / bullish 2 is a
    materially different market than one that read bearish 24. v1 stored only
    the dominant value and could not tell them apart.
    """
    d = distribution or {}
    total = sum(int(v) for v in d.values())
    if eligible_scans and total != eligible_scans:
        raise EmbeddingError(
            f"direction_distribution_incomplete: counts sum to {total} but the "
            f"segment has {eligible_scans} eligible scans")
    if total <= 0:
        raise EmbeddingError("direction_distribution_empty")
    unknown = sorted(set(d) - set(DIRECTIONS))
    if unknown:
        raise EmbeddingError(f"unsupported_direction_vocabulary:{unknown}")
    return {k: float(d.get(k, 0)) / total for k in DIRECTIONS}


# ── the encoder ──────────────────────────────────────────────────────────────
def _one_hot(value, categories, notes, group):
    vec = [0.0] * len(categories)
    v = (value or "").strip().lower() if isinstance(value, str) else ""
    if v in categories:
        vec[categories.index(v)] = 1.0
    else:
        notes.append(f"{group}:unrepresented:{value!r}")
    return vec


def embed_v2(record: dict) -> tuple:
    """(vector, notes). Raises EmbeddingError on evidence it must not guess at.

    `notes` records every group that encoded as all zeros, so an under-specified
    record is visible rather than silently similar to every other under-specified
    record.
    """
    notes, vec = [], []

    vec += _one_hot(record.get("market_regime"), REGIMES, notes, "market_regime")
    vec += _one_hot(record.get("volatility_state"), VOLATILITY, notes,
                    "volatility_state")
    vec += _one_hot(record.get("session_phase"), SESSION_PHASES, notes,
                    "session_phase")
    vec += _one_hot(record.get("narrative_phase"), NARRATIVE_PHASES, notes,
                    "narrative_phase")

    # MISSING-VALUE LAW, applied to direction too. An ABSENT distribution
    # (a live query whose direction could not be read) encodes as all zeros and
    # is noted -- it must not silently become "neutral", which would make every
    # unreadable query resemble every genuinely neutral segment. A distribution
    # that is PRESENT but malformed is a different thing entirely and raises.
    if not record.get("direction_distribution"):
        vec += [0.0] * len(DIRECTIONS)
        notes.append("direction_distribution:unknown")
    else:
        props = direction_proportions(record.get("direction_distribution"),
                                      record.get("scan_count") or 0)
        raw = [props[k] for k in DIRECTIONS]
        norm = float(np.linalg.norm(raw))
        vec += [v / norm for v in raw] if norm else [0.0] * len(DIRECTIONS)

    vec += _one_hot(record.get("delivery_state") or record.get("delivery_direction"),
                    DELIVERY_STATES, notes, "delivery_state")

    struct = record.get("structure_evidence")
    if not isinstance(struct, dict):
        raise EmbeddingError("structure_evidence_missing_or_malformed")
    # Bounded to a maximum norm of 1.0. The reachable maximum of [bos, mss, 0]
    # is sqrt(2); dividing by it keeps INTENSITY (bos=1 and bos=4 stay
    # different) while stopping a three-dimensional numeric block from
    # outweighing a categorical one purely on dimension count.
    if struct["quiet"]:
        vec += [0.0, 0.0, 1.0]
    else:
        vec += [min(1.0, struct["bos_count"] / STRUCTURE_EVENT_CAP) / _SQRT2,
                min(1.0, struct["mss_count"] / STRUCTURE_EVENT_CAP) / _SQRT2,
                0.0]

    vec += _one_hot(record.get("liquidity_state"), LIQUIDITY_STATES, notes,
                    "liquidity_state")

    draw = record.get("active_draw_present")
    if draw is None:
        vec += [0.0, 0.0]
        notes.append("active_draw:unknown")
    else:
        vec += [1.0, 0.0] if draw else [0.0, 1.0]

    vec.append(1.0 if record.get("protected_high_level") is not None else 0.0)
    vec.append(1.0 if record.get("protected_low_level") is not None else 0.0)

    exhaustion = record.get("exhaustion_present")
    if exhaustion is None:
        vec += [0.0, 0.0]
        notes.append("exhaustion:unknown")
    else:
        vec += [1.0, 0.0] if exhaustion else [0.0, 1.0]

    summary = record.get("phase_confidence_summary") or {}
    mean, lo, hi = summary.get("mean"), summary.get("min"), summary.get("max")
    if mean is None:
        vec += [0.0, 0.0]
        notes.append("confidence:unknown")
    else:
        for label, value in (("mean", mean), ("min", lo), ("max", hi)):
            if value is not None and not (CONFIDENCE_MIN <= float(value) <= CONFIDENCE_MAX):
                raise EmbeddingError(
                    f"confidence_out_of_range:{label}={value} "
                    f"(valid {CONFIDENCE_MIN}-{CONFIDENCE_MAX}; rejected, not clipped)")
        spread = (float(hi) - float(lo)) if (hi is not None and lo is not None) else 0.0
        # Bounded like structure: two coordinates must not outweigh a one-hot.
        vec += [float(mean) / CONFIDENCE_MAX / _SQRT2,
                spread / CONFIDENCE_MAX / _SQRT2]

    if len(vec) != EMBED_DIM_V2:
        raise EmbeddingError(f"dimension_mismatch: built {len(vec)}, "
                             f"manifest declares {EMBED_DIM_V2}")
    return apply_weights(vec), notes


def apply_weights(vec: list, profile: str = None) -> list:
    """Scale each block by its semantic-authority weight. Dimensionality is
    unchanged; only the geometry moves."""
    weights = block_weights(profile)
    out = list(vec)
    for g in MANIFEST["groups"]:
        w = weights[g["name"]]
        if w == 1.0:
            continue
        for i in range(g["start"], g["end"]):
            out[i] = out[i] * w
    return out


def block_norms(vec: list) -> dict:
    """Per-block norm of an already-weighted vector. Audit and telemetry."""
    return {g["name"]: float(np.linalg.norm(vec[g["start"]:g["end"]]))
            for g in MANIFEST["groups"]}


def completeness(notes: list, profile: str = None) -> dict:
    """How much of the weighted space a query actually stated.

    An unstated block contributes nothing to the numerator AND nothing to |q|,
    which RAISES cosine. Reporting and penalising it is what stops an
    underspecified query from looking more confident than a complete one.
    """
    weights = block_weights(profile)
    unknown = set()
    for note in notes:
        head = str(note).split(":", 1)[0]
        if head in weights:
            unknown.add(head)
    total = sum(w * w for w in weights.values())
    missing = sum(weights[n] ** 2 for n in unknown)
    mandatory_missing = sorted(unknown & set(MANDATORY_QUERY_BLOCKS))
    return {"score": round((total - missing) / total, 4) if total else 0.0,
            "unknown_blocks": sorted(unknown),
            "missing_mandatory": mandatory_missing,
            "complete": not unknown,
            "satisfies_mandatory": not mandatory_missing}



# ── load-bearing contradiction gate ──────────────────────────────────────────
# PROVEN NECESSARY, not chosen for convenience.
#
# The profile bake-off showed that NO weight profile separates valid analogs
# from invalid ones. A probe differing from the base state ONLY in direction
# still scores 0.8576 at load=1.50. The reason is structural: in a one-hot
# block a contradiction contributes 0 to the cosine numerator -- it never
# subtracts. With 13 blocks, one disagreement removes at most one block's w^2
# from a numerator that still carries twelve, so the floor for a single-block
# contradiction is ~0.86 at ANY weighting. Weighting moves ranking; it cannot
# express "this record contradicts the question".
#
# So contradiction is handled where it belongs -- as a RULE, not a distance.
# Weights then do what they are good at: ordering the records that do not
# contradict.

#: Categorical load-bearing blocks whose disagreement is a real contradiction.
#: Structure is absent by doctrine (brain_prompt: "STRUCTURE is a WITNESS...
#: Weigh it last"), and contextual blocks are absent by design.
CONTRADICTION_BLOCKS = ("market_regime", "volatility_state", "delivery_state",
                        "liquidity_state")

#: Below this cosine WITHIN the direction block, the two theses disagree.
#: Direction is a distribution, not a label: a segment reading bearish 8 /
#: conflicted 8 / neutral 6 / bullish 2 partially agrees with a conflicted
#: query (0.617) and is not a contradiction, while pure bullish vs pure
#: conflicted is 0.000 and is.
DIRECTION_AGREEMENT_MIN = 0.35

#: How many load-bearing contradictions a record may carry and still be offered.
#: 1 is permitted so a near-neighbour disagreeing on a single field stays
#: retrievable; 2 is refused, which is exactly the invariant that matching
#: session phase, active draw and exhaustion must not overturn contradictions in
#: both regime and direction.
MAX_LOAD_BEARING_CONTRADICTIONS = 1


def _block_slice(vec, name):
    g = _GROUP[name]
    return list(vec[g["start"]:g["end"]])


def contradiction_report(qvec: list, rvec: list) -> dict:
    """Which load-bearing blocks the two vectors actively disagree on.

    Only MUTUALLY STATED blocks count. A block one side left unstated is
    unknown, not contradicted -- silence is never evidence of disagreement.
    """
    found = []
    for name in CONTRADICTION_BLOCKS:
        a, b = _block_slice(qvec, name), _block_slice(rvec, name)
        if not any(a) or not any(b):
            continue                      # unstated on one side
        if float(np.dot(a, b)) <= 0.0:
            found.append(name)
    a = _block_slice(qvec, "direction_distribution")
    b = _block_slice(rvec, "direction_distribution")
    direction = None
    if any(a) and any(b):
        na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        direction = float(np.dot(a, b) / (na * nb)) if na and nb else 0.0
        if direction < DIRECTION_AGREEMENT_MIN:
            found.append("direction_distribution")
    return {"blocks": found, "count": len(found),
            "direction_agreement": (round(direction, 4)
                                    if direction is not None else None),
            "excluded": len(found) > MAX_LOAD_BEARING_CONTRADICTIONS}



# ── semantic recurrence law ──────────────────────────────────────────────────
# REFINE-SEMANTIC-RECURRENCE-COLLAPSE (2026-08-06).
#
# The exact-vector rule was too narrow. August 6 segments #4 and #6 agree on
# EVERY load-bearing block, on session phase, on narrative phase and on the
# direction distribution; they differ only in the structure witness (contextual)
# and in confidence (diagnostic). Their vectors are therefore not identical --
# cosine 0.9749 -- so exact-vector collapse never fired, and the two occupied
# both of the session's allowed retrieval slots. A future query would have read
# one quiet Thursday as two independent precedents, which is precisely the
# self-confirmation this whole memory class exists to prevent.
#
# Recurrence is therefore decided on SEMANTIC FIELDS, never on cosine. A high
# similarity score alone must never authorise grouping: two records can score
# 0.97 while disagreeing on delivery, and delivery is load-bearing.

#: Must match EXACTLY. These are identity and load-bearing market state.
RECURRENCE_IDENTITY_FIELDS = ("session_id", "instrument", "contract",
                              "memory_type", "authority", "outcome_validated",
                              "embedding_version",
                              "embedding_manifest_fingerprint")

#: Load-bearing categorical state. Any disagreement forbids grouping.
RECURRENCE_LOAD_BEARING_FIELDS = ("market_regime", "volatility_state",
                                  "delivery_state", "liquidity_state",
                                  "active_draw_present")

#: Contextual blocks that must ALSO match exactly in this first implementation.
#: Doctrine does not yet establish that a lunch observation and a morning one
#: are the same observation, so the conservative choice is to keep them apart.
#: August 6 shows this is the operative constraint: #3 agrees with #4/#6 on
#: every load-bearing field and on direction, and is held out only by session
#: phase and narrative phase -- correctly, since #3 is the exhaustion segment.
RECURRENCE_CONTEXTUAL_EXACT_FIELDS = ("session_phase", "narrative_phase")

#: Maximum absolute difference per direction component. Applied by QUANTISING
#: each proportion into buckets of this width, which is deterministic and
#: order-independent -- a pairwise-tolerance rule would chain transitively and
#: could group two records further apart than the tolerance allows. The
#: quantisation is conservative in the other direction: two records within
#: tolerance that straddle a bucket edge simply do not group.
DIRECTION_COMPONENT_TOLERANCE = 0.10

#: Never a grouping criterion. A more confident occurrence is not a more
#: correct one, and confidence must never PREVENT two identical market
#: observations from being recognised as the same observation either.
RECURRENCE_DIAGNOSTIC_FIELDS = ("phase_confidence_summary",)

#: Contextual differences a group may contain, reported on the analog.
RECURRENCE_PERMITTED_CONTEXTUAL_DIFFERENCES = ("structure_evidence",
                                               "structure_state",
                                               "exhaustion_present")


def _direction_bucket(record: dict) -> tuple:
    """Quantised direction distribution. None when it cannot be established."""
    dist = record.get("direction_distribution") or {}
    total = sum(int(v) for v in dist.values())
    if total <= 0 or set(dist) - set(DIRECTIONS):
        return None
    tol = DIRECTION_COMPONENT_TOLERANCE
    return tuple(int(round((dist.get(k, 0) / total) / tol)) for k in DIRECTIONS)


def semantic_recurrence_key(record: dict):
    """The deterministic grouping key, or None when it cannot be built.

    A record whose key cannot be established never groups -- unknown identity
    is not sameness.
    """
    bucket = _direction_bucket(record)
    if bucket is None:
        return None
    parts = []
    for field in RECURRENCE_IDENTITY_FIELDS + RECURRENCE_LOAD_BEARING_FIELDS \
            + RECURRENCE_CONTEXTUAL_EXACT_FIELDS:
        value = record.get(field)
        if value is None and field not in ("outcome_validated",):
            return None
        parts.append((field, value))
    # Protected structure enters as PRESENCE, matching the vector: the level
    # itself is contract-scoped and never a similarity or grouping feature.
    parts.append(("protected_high_present",
                  record.get("protected_high_level") is not None))
    parts.append(("protected_low_present",
                  record.get("protected_low_level") is not None))
    parts.append(("direction_bucket", bucket))
    return tuple(parts)


def semantic_recurrence_differences(members: list) -> dict:
    """What actually differs inside a group. Reported, never hidden."""
    contextual, diagnostic = {}, {}
    for field in RECURRENCE_PERMITTED_CONTEXTUAL_DIFFERENCES:
        values = []
        for m in members:
            v = m.get(field)
            if field == "structure_evidence" and isinstance(v, dict):
                v = {"bos_count": v.get("bos_count"),
                     "mss_count": v.get("mss_count"), "quiet": v.get("quiet")}
            if v not in values:
                values.append(v)
        if len(values) > 1:
            contextual[field] = values
    means = [(m.get("phase_confidence_summary") or {}).get("mean")
             for m in members]
    if len({m for m in means if m is not None}) > 1:
        diagnostic["confidence_mean"] = means
    return {"contextual_differences": contextual,
            "diagnostic_differences": diagnostic}


def cosine_v2(a, b) -> float:
    """Cosine over two v2 vectors. Dimension equality is the caller's gate."""
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))



# ── representative-selection projection ──────────────────────────────────────
# REMOVE-CONFIDENCE-FROM-RECURRENCE-REPRESENTATIVE (2026-08-06).
#
# The declared law said "confidence may never decide the recurrence
# representative". The representative ordering then began with FULL-VECTOR
# cosine -- and the confidence block sits in that vector at diagnostic weight
# 0.50. So confidence could still decide the representative, indirectly. A
# failing test exposed exactly this; the contradiction was real and the
# assertion should not have been rewritten around it.
#
# Ordinary retrieval similarity is UNCHANGED: it keeps using the complete
# weighted v2.1 vector, because diagnostic confidence may modestly influence
# general analog ranking. Only REPRESENTATIVE selection -- choosing which of
# several already-grouped occurrences speaks for the group -- uses a projection
# with the diagnostic block zeroed.
#
# Nothing is mutated and no second vector space is persisted: the projection is
# computed on demand from the stored vector and the authoritative manifest.

#: Feature groups removed from the representative projection, by NAME. Indices
#: are resolved from the manifest so this can never drift from the layout.
REPRESENTATIVE_EXCLUDED_GROUPS = tuple(DIAGNOSTIC_BLOCKS)


def representative_projection(vector: list) -> list:
    """The stored vector with every excluded group zeroed. Never mutates."""
    out = list(vector)
    for name in REPRESENTATIVE_EXCLUDED_GROUPS:
        g = _GROUP[name]
        for i in range(g["start"], g["end"]):
            out[i] = 0.0
    return out


#: STEP 4B.12 §4 UNIT 3 — the coordinate carrying the structure QUIET claim.
#:
#: Resolved from the manifest, never written as a literal. The group note is
#: `[bos_count/4, mss_count/4, quiet_flag]`, so quiet is the third slot. A
#: regression pins the resolved value so a future layout change cannot silently
#: make the compatibility mask exclude the wrong feature.
STRUCTURE_QUIET_INDEX = _GROUP["structure_evidence"]["start"] + 2


def legacy_manifest_fingerprint(structure_parser: str) -> str:
    """The fingerprint the CURRENT manifest would have under an older parser.

    ONE controlled substitution, on a deep copy. The global MANIFEST is never
    touched -- a fingerprint helper that mutated shared state would corrupt
    every authorization issued while it ran.

    This exists so a legacy record earns compatibility by PROVING that the
    structure parser is the only manifest-level difference. "The record says
    v1" is not sufficient: unrelated historical manifest drift must still fail
    closed.
    """
    shadow = copy.deepcopy(MANIFEST)
    shadow["parser_versions"]["structure"] = structure_parser
    blob = json.dumps(shadow, sort_keys=True, separators=(",", ":"))
    return "emb:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def excluded_projection(vector: list, excluded) -> list:
    """The vector with `excluded` coordinates zeroed. Never mutates the input.

    Zeroing BOTH sides of a comparison is exactly exclusion: the coordinate then
    contributes nothing to the dot product and nothing to either norm. Zeroing
    only one side would be worse than useless -- it would keep the coordinate in
    the other vector's norm and quietly depress the score.
    """
    if not excluded:
        return list(vector)
    out = list(vector)
    for i in excluded:
        out[i] = 0.0
    return out


def compatible_cosine(qvec: list, rvec: list, excluded=()) -> float:
    """Cosine over only the mutually authoritative coordinates."""
    return cosine_v2(excluded_projection(qvec, excluded),
                     excluded_projection(rvec, excluded))


def representative_similarity(qvec: list, rvec: list, excluded=()) -> float:
    """Cosine used ONLY to choose a recurrence group's representative.

    Excludes the diagnostic block on both sides, so no confidence value can
    reach the decision -- not through the numerator and not through either
    norm.

    UNIT 3: `excluded` carries any cross-version incompatible coordinates on
    top of that. Representative selection is a comparison like any other, so a
    coordinate the current contract cannot lawfully compare may not decide which
    occurrence speaks for a group either.
    """
    return cosine_v2(
        excluded_projection(representative_projection(qvec), excluded),
        excluded_projection(representative_projection(rvec), excluded))

def describe_indices(vector) -> list:
    """Human-readable active features. Review and telemetry only."""
    out = []
    for g in MANIFEST["groups"]:
        for i in range(g["start"], g["end"]):
            v = vector[i]
            if not v:
                continue
            if g["categories"]:
                out.append(f"{g['name']}:{g['categories'][i - g['start']]}")
            else:
                out.append(f"{g['name']}[{i - g['start']}]={round(float(v), 4)}")
    return out
