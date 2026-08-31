"""
Phase AB-3 — Retrieval API + audit logging.

Given the current snapshot/context, return the nearest historical analogs by
market-state cosine similarity. Authoritative retrieval excludes structure-
tainted and non-validated-provenance records (Requirement 3 / T2).

OBSERVE-ONLY: this module retrieves and logs. It does not author, qualify,
select, approve, or execute anything (Requirement 7). Never raises.
"""
import json
import os
from datetime import datetime

import pytz

from doctrine.instrument_identity import record_instrument, retrieval_eligible
from ai_retrieval import descriptive_memory as DM
from ai_retrieval import embedding_v2 as EV2
from ai_retrieval import retrieval_contract as RC
from ai_retrieval.embedding import embed, cosine
from ai_retrieval.memory_schema import is_authoritative
from ai_retrieval.vector_store import load_records

_EASTERN = pytz.timezone("America/New_York")


def _today_et() -> str:
    """The current ET SESSION date. Age is a session question, not a UTC one."""
    return datetime.now(_EASTERN).strftime("%Y-%m-%d")


def _query_contract(context: dict) -> str:
    c = context or {}
    for key in ("contract", "contract_id", "active_contract"):
        if c.get(key):
            return str(c[key])
    for nest in ("market", "metadata", "market_context"):
        block = c.get(nest)
        if isinstance(block, dict):
            for key in ("contract", "contract_id", "active_contract"):
                if block.get(key):
                    return str(block[key])
    return ""


def _log_dir() -> str:
    return os.path.join(os.getenv("AI_RETRIEVAL_DIR", os.path.join("data", "ai_retrieval")),
                        "retrieval_logs")


#: The sanctioned boolean forms, shared with the Brain's JSON-mode predicate.
#: The original check accepted only the literal "true", so
#: `AI_RETRIEVAL_ENABLED=on` would read as DISABLED to the runtime while looking
#: enabled to an operator -- the same class of defect as the JSON-mode flag on
#: 2026-08-06.
RETRIEVAL_TRUTHY = ("on", "true", "1", "yes")


def retrieval_enabled() -> bool:
    """THE single source of truth for descriptive-memory retrieval.

    Every caller -- the scan-loop hook, the startup guard, the authorization
    verifier and telemetry -- resolves through here, because they must not be
    able to disagree. Defaults to DISABLED: retrieval is never inferred from the
    corpus being non-empty, it is stated.
    """
    return raw_retrieval_flag().lower().strip() in RETRIEVAL_TRUTHY


def raw_retrieval_flag() -> str:
    """Exactly what the environment says, for telemetry and refusal messages."""
    return os.getenv("AI_RETRIEVAL_ENABLED") or ""


def retrieval_startup_state() -> dict:
    """Resolved memory-startup state. Read-only; never raises.

    ENFORCE-MEMORY-RETRIEVAL-ENABLEMENT-AUTHORITY (2026-08-07). The August 6
    corpus was authored and then discovered, the next morning, to be
    unreachable: `AI_RETRIEVAL_ENABLED` was absent, so `retrieve_for_snapshot`
    short-circuited before ever reading the ten records. Ten memories on disk
    and zero reaching the Brain, with every other telemetry line healthy.
    """
    from ai_retrieval import descriptive_memory as _DM
    try:
        records = load_records()
    except Exception:  # noqa: BLE001
        records = []
    descriptive = [r for r in records
                   if r.get("memory_type") == _DM.MEMORY_TYPE_DESCRIPTIVE]
    enabled = retrieval_enabled()
    if descriptive and not enabled:
        state = "MEMORY_PRESENT_BUT_RETRIEVAL_DISABLED"
    elif not descriptive and not enabled:
        state = "empty-allowed"
    else:
        state = "ready"
    return {"enabled": enabled, "raw_flag": raw_retrieval_flag(),
            "resolution_source": "ai_retrieval.retrieval.retrieval_enabled",
            "record_count": len(records),
            "descriptive_records": len(descriptive),
            "state": state,
            "refuses_armed_startup": state == "MEMORY_PRESENT_BUT_RETRIEVAL_DISABLED"}


def _enabled() -> bool:
    """Back-compat alias. Delegates -- never re-implements the parse."""
    return retrieval_enabled()


def _descriptive_view(rec: dict, score: float, query_contract: str) -> dict:
    """A descriptive analog, with its authority stated on the record itself.

    The framing travels WITH the analog rather than living once in the prompt
    header. A single header is one sentence the model can drift past after five
    records; a per-record label cannot be separated from the data it labels.
    """
    view = {
        "similarity": round(score, 4),
        "memory_type": rec.get("memory_type"),
        "authority": rec.get("authority"),
        "outcome_validated": rec.get("outcome_validated"),
        "recommendation_authority": rec.get("recommendation_authority"),
        "execution_authority": rec.get("execution_authority"),
        "framing": RC.ANALOG_FRAMING,
        "session_date": rec.get("session_date"),
        "segment": f"{rec.get('segment_start')}-{rec.get('segment_end')} ET",
        "scan_count": rec.get("scan_count"),
        "session_phase": rec.get("session_phase"),
        "market_regime": rec.get("market_regime"),
        "volatility_state": rec.get("volatility_state"),
        "delivery_state": rec.get("delivery_state"),
        "structure_state": rec.get("structure_state"),
        "structure_evidence": rec.get("structure_evidence"),
        "liquidity_state": rec.get("liquidity_state"),
        "active_draw_present": rec.get("active_draw_present"),
        "exhaustion_present": rec.get("exhaustion_present"),
        "embedding_version": rec.get("embedding_version"),
        "memory_id": rec.get("memory_id"),
        "session_id": rec.get("session_id"),
        "dominant_direction": rec.get("dominant_direction"),
        "dominant_action": rec.get("dominant_action"),
        "direction_distribution": rec.get("direction_distribution"),
        "candidate_count": rec.get("candidate_count"),
        "trade_count": rec.get("trade_count"),
        "no_candidate_reasons": rec.get("no_candidate_reasons"),
        "source_model": rec.get("source_model"),
    }
    # Absolute levels are contract-scoped. Across a rollover the same number is
    # a price on a different instrument-month, and comparing it to today's book
    # is a units error dressed up as an analog. The categorical features stay.
    same_contract = (not query_contract
                     or str(rec.get("contract") or "") == str(query_contract))
    if same_contract or not RC.WITHHOLD_LEVELS_ACROSS_CONTRACTS:
        view["protected_high"] = rec.get("protected_high_level")
        view["protected_low"] = rec.get("protected_low_level")
        view["protected_high_timeframe"] = rec.get("protected_high_timeframe")
        view["protected_low_timeframe"] = rec.get("protected_low_timeframe")
        view["levels_withheld"] = False
    else:
        view["levels_withheld"] = True
        view["levels_withheld_reason"] = (
            f"recorded on {rec.get('contract')}, query on {query_contract}")
    return view


def _analog_view(rec: dict, score: float, query_contract: str = "") -> dict:
    if rec.get("memory_type") == DM.MEMORY_TYPE_DESCRIPTIVE:
        return _descriptive_view(rec, score, query_contract)
    nc = rec.get("narrative_context", {}) or {}
    oc = rec.get("outcome_context", {}) or {}
    pc = rec.get("playbook_context", {}) or {}
    mc = rec.get("market_context", {}) or {}
    return {
        "similarity": round(score, 4),
        "timestamp": mc.get("timestamp"),
        "regime": mc.get("regime"),
        "narrative_direction": nc.get("narrative_direction"),
        "narrative_phase": nc.get("narrative_phase"),
        "delivery_direction": nc.get("delivery_direction"),
        "active_liquidity_draw": nc.get("active_liquidity_draw"),
        "active_playbook": pc.get("active_playbook"),
        "trade_taken": oc.get("trade_taken"),
        "outcome": oc.get("win_loss_be"),
        "r_multiple": oc.get("r_multiple"),
        "management_path": oc.get("management_path"),
        "direction_source": (rec.get("provenance", {}) or {}).get("direction_source"),
    }



def _resolve_vector_space(records: list) -> str:
    """"v2" when the corpus holds any descriptive record, else "legacy".

    Not a compatibility MODE -- the two are never mixed in one ranking. This
    only decides which single space a given corpus is read in.
    """
    for rec in records:
        if rec.get("memory_type") == DM.MEMORY_TYPE_DESCRIPTIVE:
            return "v2"
    return "legacy"


# STEP 4B.12 §4 UNIT 3 — THE SINGLE VECTOR-COMPATIBILITY OWNER.
#
# The structure parser moved v1 -> v2 because v2 refuses to call an unevaluable
# read "quiet". The whole-manifest gate then refused all 16 historical records,
# which is TOO COARSE: measured across the entire corpus, exactly ONE coordinate
# changed meaning and nothing else moved at all.
#
#     dimensionality            58 -> 58 on all 16
#     BOS/MSS counts            unchanged on all 16
#     changed feature indices   union = {45}, the structure quiet flag
#     other descriptive fields  zero changes
#
# So the honest statement is not "v1 memory is invalid". It is "v1 and v2 are
# comparable except where v1 lacked the evidence to authorize the quiet claim":
#
#   CASE A, 13 records: a POSITIVE bos/mss event independently proves the market
#       was not quiet. Missing evaluability cannot un-happen an observed break,
#       so all 58 coordinates stay comparable.
#   CASE B, 3 records: zero events and a stored quiet=True. v1 read that from
#       ABSENCE alone. Dimension 45 is incomparable; the other 57 are evidence.
#
# Nothing here rewrites, coerces, or repairs a stored value. The exclusion is
# comparison-time only, and the record on disk keeps saying exactly what v1
# authored.
COMPAT_FULL = "FULL"
COMPAT_PARTIAL = "PARTIAL"
COMPAT_INCOMPATIBLE = "INCOMPATIBLE"

_LEGACY_STRUCTURE_PARSER = "structure_witness_v1"


def _incompatible(reason: str) -> dict:
    return {"mode": COMPAT_INCOMPATIBLE, "compatible": False,
            "excluded_dimensions": frozenset(), "reason": reason}


def vector_compatibility(rec: dict) -> dict:
    """Whether this record's vector may be compared, and on which coordinates.

    ONE owner. Cosine, representative selection and the contradiction gate all
    read this result; a second mapping anywhere would be a second authority for
    the same epistemic question.
    """
    if rec.get("embedding_version") != EV2.EMBEDDING_VERSION:
        return _incompatible("embedding_version_mismatch")
    vec = rec.get("feature_vector")
    if not isinstance(vec, list) or len(vec) != EV2.EMBED_DIM_V2:
        return _incompatible("embedding_dimension_mismatch")
    try:
        if EV2.vector_fingerprint(vec) != rec.get("feature_vector_fingerprint"):
            return _incompatible("feature_vector_fingerprint_mismatch")
    except (TypeError, ValueError):
        return _incompatible("feature_vector_malformed")

    stored_fp = rec.get("embedding_manifest_fingerprint")
    if stored_fp == EV2.manifest_fingerprint():
        return {"mode": COMPAT_FULL, "compatible": True,
                "excluded_dimensions": frozenset(), "reason": ""}

    # A record does NOT earn the legacy bridge by claiming to be v1. It must
    # prove that the structure parser is the ONLY manifest-level difference:
    # the current manifest with exactly one controlled substitution must hash to
    # what the record stored. Unrelated historical manifest drift still fails
    # closed here, which is the whole point of deriving the expectation instead
    # of trusting the label.
    se = rec.get("structure_evidence")
    if not isinstance(se, dict) or se.get("parser") != _LEGACY_STRUCTURE_PARSER:
        return _incompatible("embedding_manifest_mismatch")
    if stored_fp != EV2.legacy_manifest_fingerprint(_LEGACY_STRUCTURE_PARSER):
        return _incompatible("embedding_manifest_mismatch")

    bos, mss, quiet = se.get("bos_count"), se.get("mss_count"), se.get("quiet")
    if not isinstance(bos, int) or not isinstance(mss, int) or not isinstance(quiet, bool):
        return _incompatible("legacy_structure_evidence_malformed")

    if bos > 0 or mss > 0:
        if quiet:
            # The record contradicts its own structure evidence. Not ours to
            # repair, and not safe to compare.
            return _incompatible("legacy_structure_self_contradiction")
        return {"mode": COMPAT_FULL, "compatible": True,
                "excluded_dimensions": frozenset(),
                "reason": "legacy_v1_positive_event_proves_not_quiet"}

    if quiet:
        return {"mode": COMPAT_PARTIAL, "compatible": True,
                "excluded_dimensions": frozenset({EV2.STRUCTURE_QUIET_INDEX}),
                "reason": "legacy_v1_quiet_unauthorised_under_v2"}

    # Zero events and quiet=False. ZERO examples exist in the measured corpus,
    # so the semantics are unproven and this fails closed rather than guessing
    # that it is harmless.
    return _incompatible("legacy_v1_zero_event_non_quiet_unmeasured")


def _vector_incompatible(rec: dict) -> str:
    """Binary view for callers that only need refusal, "" when comparable.

    Kept as a wrapper so no caller silently loses the exclusion mask: anything
    that actually COMPARES vectors must read `vector_compatibility` instead.
    """
    compat = vector_compatibility(rec)
    return "" if compat["compatible"] else compat["reason"]


_TF_ORDER = ("15m", "5m", "3m", "1m")


def _has_timeframe_shape(liq: dict) -> bool:
    return any(isinstance(liq.get(tf), dict) for tf in _TF_ORDER)


def _liquidity_from_timeframes(liq: dict) -> tuple:
    """Flatten a snapshot-shaped liquidity block exactly as brain_input does."""
    def first(key):
        for tf in _TF_ORDER:
            block = liq.get(tf)
            if isinstance(block, dict) and block.get(key) is not None:
                return block[key]
        return None
    return first("nearest_buy_side_liquidity"), first("nearest_sell_side_liquidity")


def query_vector(context: dict) -> tuple:
    """Embed a live snapshot into the SAME v2 space the corpus lives in.

    The query is translated into the descriptive record shape and handed to the
    one encoder. A separate query encoder would be a second implementation of
    the layout, and the two would drift.
    """
    ctx = context or {}
    mr = ctx.get("market_regime") or {}
    na = ctx.get("narrative_authority") or {}
    sc = ctx.get("shared_context") or {}
    ps = ctx.get("protected_swings") or {}
    liq = ctx.get("liquidity") or {}
    # A live scan has ONE direction, so its distribution is a point mass. An
    # unreadable direction stays EMPTY and encodes as all zeros -- it must not
    # become "neutral", which would make every unreadable query resemble every
    # genuinely neutral segment in the corpus.
    direction = (na.get("narrative_direction") or "").strip().lower()
    dist = {direction: 1} if direction in EV2.DIRECTIONS else {}
    scans = sum(dist.values())

    # PROD-20260807 DEFECT. `build_snapshot` emits liquidity keyed BY TIMEFRAME
    # ({"15m": {"nearest_buy_side_liquidity": ...}, ...}); only `brain_input`
    # flattens it. Reading the flattened keys off the raw snapshot returned None
    # for both sides while the dict was non-empty, so the "unknown" guard never
    # fired and every live query resolved to a confident `no_pools`. The market
    # actually had two-sided pools on 142/151 scans, so all ten August 6 records
    # contradicted on liquidity_state 1027/1027 times.
    #
    # Accept BOTH shapes, using the same first-non-null-across-timeframes rule
    # `brain_input` uses, so one raw snapshot yields one liquidity state.
    buy = liq.get("nearest_buy_side", ctx.get("nearest_buy_side"))
    sell = liq.get("nearest_sell_side", ctx.get("nearest_sell_side"))
    if buy is None and sell is None:
        buy, sell = _liquidity_from_timeframes(liq)
    if buy is None and sell is None and not liq:
        # No liquidity block supplied at all: unknown, not "no pools".
        liquidity = None
    elif buy is None and sell is None and not _has_timeframe_shape(liq):
        liquidity = None
    else:
        liquidity = EV2.liquidity_state(buy, sell)

    witness = ctx.get("STRUCTURE_WITNESS") or ctx.get("structure_witness")
    try:
        structure = EV2.structure_evidence(witness)
    except EV2.EmbeddingError:
        # UNIT 3 — an absent witness already refused to claim quiet here. The
        # capability now SAYS so in the same vocabulary the present-witness path
        # uses, so a consumer reads one contract rather than two.
        structure = {"bos_count": 0, "mss_count": 0, "quiet": False,
                     "structure_capability": "UNKNOWN", "unavailable": True}

    def level(block):
        return block.get("level") if isinstance(block, dict) else block

    shaped = {
        "market_regime": mr.get("regime_label"),
        "volatility_state": mr.get("volatility_state"),
        "session_phase": ctx.get("session"),
        "narrative_phase": na.get("narrative_phase"),
        "direction_distribution": dist,
        "scan_count": scans,
        "delivery_state": sc.get("delivery_state"),
        "structure_evidence": structure,
        "liquidity_state": liquidity,
        "active_draw_present": (None if na.get("active_liquidity_draw") is None
                                and "active_liquidity_draw" not in na
                                else bool(na.get("active_liquidity_draw"))),
        "exhaustion_present": sc.get("exhaustion_present"),
        "protected_high_level": level(ps.get("protected_high")),
        "protected_low_level": level(ps.get("protected_low")),
        "phase_confidence_summary": ctx.get("phase_confidence_summary") or {},
    }
    return EV2.embed_v2(shaped)


def retrieve_analogs(context: dict, k: int = None, authoritative_only: bool = True,
                     min_similarity: float = None, persist_log: bool = True,
                     today: str = None) -> dict:
    """
    Return top-k historical analogs of `context` (a live snapshot-shaped dict or
    a memory record). Logs query + accepted + rejected for auditability (T7).
    Never raises; observe-only.

    `k` and `min_similarity` default to the BOUND retrieval contract rather than
    to literals, so the values the authorization fingerprints are the values
    production actually applies.
    """
    try:
        k = RC.MAX_ANALOGS if k is None else k
        min_similarity = (RC.MIN_SIMILARITY if min_similarity is None
                          else min_similarity)
        today = today or _today_et()
        qcontract = _query_contract(context)
        records = load_records()
        # ONE space per call. Descriptive memory lives in
        # descriptive.embedding.v2; the legacy AB-3 market/trade records live in
        # the 47-dimension space. Cosine BETWEEN them is arithmetic without
        # meaning, so they are never ranked in the same list: a corpus holding
        # any descriptive record is read as a v2 corpus and legacy rows are
        # excluded with a reason. Production only ever authors descriptive
        # records, so production is always the v2 branch.
        space = _resolve_vector_space(records)
        if space == "v2":
            qvec, qnotes = query_vector(context)
            comp = EV2.completeness(qnotes)
        else:
            qvec, qnotes, comp = embed(context), [], None

        # QUERY COMPLETENESS LAW. A query that omits a load-bearing block is not
        # a looser question, it is an unanswerable one -- and answering it
        # anyway REWARDS the omission, because an unstated block shrinks |q|
        # while contributing nothing to either side. Refusing is the only
        # treatment that cannot be gamed by asking less.
        if comp and not comp["satisfies_mandatory"]:
            return {"enabled": True, "authority": "observe_only",
                    "retrieval_authority": RC.AUTHORITY_LABEL,
                    "vector_space": space,
            "completeness": comp,
            "incomplete_query": bool(comp and not comp["complete"]),
            "weight_profile": EV2.ACTIVE_PROFILE,
            "block_weights": EV2.block_weights(), "analogs": [], "returned": 0,
                    "corpus_size": len(records),
                    "incomplete_query": True,
                    "completeness": comp,
                    "refusal": "INCOMPLETE_QUERY_MISSING_MANDATORY_BLOCKS",
                    "missing_mandatory_blocks": comp["missing_mandatory"],
                    "mandatory_query_blocks": list(EV2.MANDATORY_QUERY_BLOCKS)}

        scored, rejected, gated_detail = [], [], []
        for rec in records:
            # Retention is a RETRIEVAL rule. The record stays on disk for audit;
            # it simply stops being offered as an analog. A record whose age
            # cannot be established is treated as expired, not as young.
            if rec.get("memory_type") == DM.MEMORY_TYPE_DESCRIPTIVE:
                if DM.is_expired(rec, today):
                    rejected.append({"reason": "expired",
                                     "session_date": rec.get("session_date"),
                                     "expires_at": rec.get("expires_at")})
                    continue
                if rec.get("authority") != RC.AUTHORITY_LABEL:
                    rejected.append({"reason": "authority_label_mismatch",
                                     "authority": rec.get("authority")})
                    continue
                if rec.get("outcome_validated") is not False:
                    rejected.append({"reason": "descriptive_record_claims_outcome"})
                    continue
            # DECON-3: instrument identity is checked BEFORE similarity. A QQQ
            # session can resemble an MNQ one closely — similarity is exactly
            # what would let equity evidence look like a good analog for a
            # futures decision. Unlabelled records are excluded, not assumed
            # compatible.
            eligible, why = retrieval_eligible(rec)
            if not eligible:
                rejected.append({"reason": why,
                                 "instrument": record_instrument(rec)})
                continue
            descriptive = rec.get("memory_type") == DM.MEMORY_TYPE_DESCRIPTIVE
            if space == "v2":
                if not descriptive:
                    rejected.append({"reason": "legacy_record_in_v2_corpus",
                                     "memory_type": rec.get("memory_type")})
                    continue
                # Vector-space compatibility is a HARD gate. A layout mismatch
                # would silently return a number rather than fail.
                # UNIT 3 — the compatibility OWNER, not the binary wrapper. A
                # PARTIAL record is comparable, but only on the coordinates the
                # current contract can lawfully read, so the mask has to travel
                # with the record into every score below.
                compat = vector_compatibility(rec)
                if not compat["compatible"]:
                    rejected.append({"reason": compat["reason"],
                                     "embedding_version": rec.get("embedding_version")})
                    continue
                excluded = compat["excluded_dimensions"]
                # Contradiction gate BEFORE similarity. A record disagreeing
                # with the question on more than one load-bearing block is not
                # a weak analog to be ranked low -- it is an answer to a
                # different question, and no threshold can express that.
                contra = EV2.contradiction_report(qvec, rec["feature_vector"])
                if contra["excluded"]:
                    entry = {"reason": "load_bearing_contradiction",
                             "blocks": contra["blocks"],
                             "direction_agreement": contra["direction_agreement"]}
                    rejected.append(entry)
                    gated_detail.append(entry)
                    continue
                score = EV2.compatible_cosine(qvec, rec["feature_vector"],
                                              excluded)
                # Optional blocks the query left unstated still inflate cosine
                # by shrinking |q|. The completeness factor removes exactly
                # that advantage, and is reported rather than hidden.
                if comp and comp["score"] < 1.0:
                    score *= comp["score"]
            else:
                if descriptive:
                    rejected.append({"reason": "descriptive_record_in_legacy_corpus"})
                    continue
                score = cosine(qvec, rec.get("embedding") or embed(rec))
            authoritative = is_authoritative(rec)
            if authoritative_only and not authoritative:
                rejected.append({"reason": "non_authoritative_provenance",
                                 "direction_source": (rec.get("provenance", {}) or {}).get("direction_source"),
                                 "similarity": round(score, 4)})
                continue
            if score < min_similarity:
                rejected.append({"reason": "below_min_similarity",
                                 "similarity": round(score, 4)})
                continue
            scored.append((score, rec))

        # ORDER MATTERS: rank -> collapse same-session recurrence -> cap per
        # session -> take k. Collapsing after top-k would already have spent the
        # slots; capping before collapse would drop occurrences that were about
        # to merge into one anyway.
        scored.sort(key=lambda pair: ranking_tuple(pair[0], pair[1]))
        pre_collapse = len(scored)
        scored, collapsed = collapse_recurrence(scored, qvec)
        scored, capped = apply_session_cap(scored, RC.MAX_ANALOGS_PER_SOURCE_SESSION)
        top = scored[:k]
        analogs = []
        for score, rec in top:
            view = _analog_view(rec, score, qcontract)
            view["ranking_tuple"] = [str(x) for x in ranking_tuple(score, rec)]
            if rec.get("recurrence_count"):
                # Every occurrence travels with the analog, so a group is
                # visibly one observation seen N times -- never N precedents.
                for field in ("recurrence_type", "recurrence_count",
                              "occurrence_spans", "grouped_memory_ids",
                              "member_similarities",
                              "member_representative_similarities",
                              "representative_memory_id",
                              "contextual_differences", "diagnostic_differences"):
                    view[field] = rec.get(field)
            analogs.append(view)

        result = {
            "enabled": True,
            "authority": "observe_only",
            "retrieval_authority": RC.AUTHORITY_LABEL,
            "framing": RC.ANALOG_FRAMING,
            "query_embedding_dim": len(qvec),
            "query_contract": qcontract,
            "corpus_size": len(records),
            "authoritative_only": authoritative_only,
            "max_analogs": k,
            "max_analogs_per_source_session": RC.MAX_ANALOGS_PER_SOURCE_SESSION,
            "min_similarity": min_similarity,
            "vector_space": space,
            "completeness": comp,
            "incomplete_query": bool(comp and not comp["complete"]),
            "weight_profile": EV2.ACTIVE_PROFILE,
            "block_weights": EV2.block_weights(),
            "embedding_version": (EV2.EMBEDDING_VERSION if space == "v2"
                                  else "legacy.47"),
            "embedding_manifest_fingerprint": (EV2.manifest_fingerprint()
                                               if space == "v2" else None),
            "query_embedding_notes": qnotes,
            "pre_collapse_candidates": pre_collapse,
            "recurrence_groups_collapsed": collapsed,
            "per_session_cap_exclusions": capped,
            "tie_break_order": list(RC.TIE_BREAK_ORDER),
            "max_age_days": RC.MAX_AGE_DAYS,
            "as_of_session_date": today,
            "returned": len(analogs),
            "analogs": analogs,
            "rejected_count": len(rejected),
            "rejected_reasons": dict(_count_reasons(rejected)),
            # Per-record contradiction detail, for telemetry reason accounting.
            # Occurrences exceed gated-record count when one record contradicts
            # on several blocks; the two must never be conflated.
            "_gated_detail": gated_detail,
        }

        if persist_log:
            result["log_path"] = _persist(qvec, analogs, rejected, context)
        return result
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "authority": "observe_only",
                "retrieval_authority": RC.AUTHORITY_LABEL, "analogs": [],
                "error": f"retrieval error (observe-only): {exc}"}



# ── ranking, recurrence and diversity ────────────────────────────────────────
def _seconds(hhmmss) -> int:
    try:
        parts = [int(x) for x in str(hhmmss).split(":")]
        while len(parts) < 3:
            parts.append(0)
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except (TypeError, ValueError):
        return 0


def segment_duration(rec: dict) -> int:
    """Segment length in seconds. 0 when the span cannot be read."""
    return max(0, _seconds(rec.get("segment_end")) - _seconds(rec.get("segment_start")))


def ranking_tuple(score: float, rec: dict) -> tuple:
    """RC.TIE_BREAK_ORDER, made concrete and sortable ascending.

    v1 sorted on similarity alone. Python's sort is stable, so every tie fell
    through to JSONL append order -- ranking depended on the order records
    happened to be written, which is not a rule, it is an accident that happens
    to be reproducible.
    """
    return (-round(float(score), 12),
            _negated_date(rec.get("session_date")),
            -int(rec.get("scan_count") or 0),
            -segment_duration(rec),
            str(rec.get("memory_id") or ""))


def _negated_date(session_date) -> str:
    """Descending session date as an ascending sort key."""
    digits = "".join(ch for ch in str(session_date or "") if ch.isdigit())[:8]
    if len(digits) != 8:
        return "99999999"          # undated sorts last, never first
    return str(99999999 - int(digits)).zfill(8)


def _representative(group: list) -> dict:
    """RC.RECURRENCE_REPRESENTATIVE_ORDER. Confidence is NOT a criterion."""
    return sorted(group, key=lambda r: (-int(r.get("scan_count") or 0),
                                        -segment_duration(r),
                                        _seconds(r.get("segment_start")),
                                        str(r.get("memory_id") or "")))[0]


def collapse_recurrence(scored: list, qvec: list) -> tuple:
    """Collapse same-session recurrent observations to one analog.

    Grouping is decided on SEMANTIC FIELDS (`embedding_v2.semantic_recurrence_key`),
    never on cosine. Two records can score 0.97 while disagreeing on delivery,
    and delivery is load-bearing -- a similarity score is not evidence that two
    observations are the same observation.

    A group shares ONE retrieval slot and exposes every occurrence, so the
    repetition stays visible without being able to vote twice. Records from
    DIFFERENT sessions never group: the same state on another day is
    independent evidence.

    Runs AFTER identity, version, expiry, contradiction gating and scoring, and
    BEFORE the per-session cap and top-k -- collapsing later would already have
    spent the slots.
    """
    if not RC.RECURRENCE_COLLAPSE_SAME_SESSION:
        return scored, []
    groups, order = {}, []
    for score, rec in scored:
        key = EV2.semantic_recurrence_key(rec)
        if key is None:
            # Unknown identity is not sameness. Such a record stands alone.
            key = ("__ungroupable__", id(rec))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((score, rec))

    out, collapsed = [], []
    for key in order:
        members = groups[key]
        if len(members) == 1:
            out.append(members[0])
            continue
        rep_score, rep = _representative(members, qvec)
        records = [r for _, r in members]
        fingerprints = {r.get("feature_vector_fingerprint") for r in records}
        rep = dict(rep)
        rep["recurrence_type"] = ("exact_same_session" if len(fingerprints) == 1
                                  else "semantic_same_session")
        rep["recurrence_count"] = len(members)
        rep["occurrence_spans"] = sorted(
            f"{r.get('segment_start')}-{r.get('segment_end')}" for r in records)
        rep["grouped_memory_ids"] = sorted(str(r.get("memory_id"))
                                           for r in records)
        rep["member_similarities"] = {str(r.get("memory_id")): round(s, 4)
                                      for s, r in members}
        # Both are reported so the selection is auditable: the group is RANKED
        # by retrieval similarity and REPRESENTED by the confidence-free one.
        # UNIT 3 — PER-RECORD, never per-group. Two members of one recurrence
        # group can carry different compatibility: a v1 record with a positive
        # BOS keeps all 58 coordinates, while a v1 record whose quiet came from
        # absence keeps 57. Taking one member's exclusion set and applying it to
        # the group would either blind a comparable record or expose an
        # unauthorised one.
        rep["member_representative_similarities"] = {
            str(r.get("memory_id")):
                round(EV2.representative_similarity(
                    qvec, r["feature_vector"],
                    vector_compatibility(r)["excluded_dimensions"]), 4)
            for _, r in members}
        rep["representative_memory_id"] = rep.get("memory_id")
        rep.update(EV2.semantic_recurrence_differences(records))
        out.append((rep_score, rep))
        collapsed.append({"session_id": records[0].get("session_id"),
                          "recurrence_type": rep["recurrence_type"],
                          "count": len(members),
                          "representative": rep["representative_memory_id"],
                          "grouped_memory_ids": rep["grouped_memory_ids"],
                          "spans": rep["occurrence_spans"],
                          "contextual_differences": rep["contextual_differences"],
                          "diagnostic_differences": rep["diagnostic_differences"]})
    out.sort(key=lambda pair: ranking_tuple(pair[0], pair[1]))
    return out, collapsed


def _representative(members: list, qvec: list) -> tuple:
    """RC.RECURRENCE_REPRESENTATIVE_ORDER, on a CONFIDENCE-FREE projection.

    Similarity to the current query leads, so the group is represented by its
    most relevant occurrence -- but that similarity is computed with the
    diagnostic block zeroed on both sides. Ranking on the full vector would let
    confidence decide the representative indirectly, which is precisely what the
    declared law forbids.

    The returned score is still the FULL retrieval similarity, because that is
    what the analog is ranked and reported by.
    """
    ordered = sorted(
        members,
        key=lambda pair: (
            -round(EV2.representative_similarity(
                qvec, pair[1]["feature_vector"],
                vector_compatibility(pair[1])["excluded_dimensions"]), 12),
            -int(pair[1].get("scan_count") or 0),
            -segment_duration(pair[1]),
            _seconds(pair[1].get("segment_start")),
            str(pair[1].get("memory_id") or "")))
    return ordered[0]


def apply_session_cap(scored: list, cap: int) -> tuple:
    """At most `cap` analogs from any one source session. Order preserved."""
    kept, dropped, seen = [], [], {}
    for score, rec in scored:
        sid = rec.get("session_id") or "<unknown>"
        seen[sid] = seen.get(sid, 0) + 1
        if cap and seen[sid] > cap:
            dropped.append({"reason": "per_session_cap", "session_id": sid,
                            "memory_id": rec.get("memory_id"),
                            "similarity": round(score, 4)})
            continue
        kept.append((score, rec))
    return kept, dropped


def _count_reasons(rejected: list) -> dict:
    counts = {}
    for r in rejected:
        key = str(r.get("reason") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _persist(qvec, analogs, rejected, context) -> "str | None":
    try:
        d = _log_dir()
        os.makedirs(d, exist_ok=True)
        ts = datetime.now(_EASTERN).strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(d, f"retrieval_{ts}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({
                "query_timestamp": context.get("timestamp"),
                "query_vector": qvec,
                "accepted_memories": analogs,
                "rejected_memories": rejected,
                "provenance_status": {
                    "accepted": len(analogs),
                    "rejected_non_authoritative": sum(
                        1 for r in rejected if r.get("reason") == "non_authoritative_provenance"),
                },
            }, fh, default=str)
        return path
    except Exception:  # noqa: BLE001
        return None


def retrieve_for_snapshot(snapshot: dict, symbol: str) -> dict:
    """Scan-loop hook (observe-only). Gated by AI_RETRIEVAL_ENABLED."""
    if not _enabled():
        return {"enabled": False, "authority": "observe_only",
                "retrieval_authority": RC.AUTHORITY_LABEL, "analogs": []}
    return retrieve_analogs(snapshot, authoritative_only=True)
