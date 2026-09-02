"""Luna thesis -> CandidateSnapshot. A translator, never a decision-maker.

This is the bridge between the intelligence layer and the protected execution
path. Everything it emits was already decided elsewhere: Luna chose the
direction, the invalidation and the draw; the mechanical layer enumerated what
actually exists in the snapshot. The producer's only job is to prove those two
agree, and to refuse when they do not.

WHAT IT MUST NEVER DO, stated as code-level rules:

  * fabricate a target because Luna omitted one
  * fabricate a stop because the risk engine wants one
  * substitute the next-farther objective when Luna's is spent
  * pick whichever objective maximises R
  * build the venue bracket (that happens at submit time, on the current price)

A stand-down produces no candidate. That is the system working, not failing —
most scans should end here.

THE RESOLUTION RULE. Luna names a draw in `active_draw` as prose. The producer
resolves that name against objectives the mechanical layer actually enumerated
from the same snapshot. If the name cannot be matched to exactly one real
objective, there is NO CANDIDATE — because a target nobody can point to on the
chart is not a target.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from broker.topstepx_candidate_freshness import (
    OBJECTIVE_KINDS, CandidateSnapshot, LiquidityObjective,
)

DEFAULT_TTL_SECONDS = 120.0        # two scan cadences; a candidate is perishable
# UPGRADE-...-TERRA (2026-08-06): imported from the SINGLE authority rather
# than restated. This was a hardcoded "gpt-5.6-luna" -- a second source of truth
# that would have rejected every Terra thesis as `wrong_model` and silently
# blocked all trading after the migration, with no other symptom.
from ai_brain.production_model import PRODUCTION_MODEL
# STEP 7 — the approved family vocabulary, owned beside the validator so an
# unknown token can only ever fail closed.
from ai_brain.brain_validation import CONCRETE_TOOL_FAMILIES
# RR-FLOOR-1.0 (2026-08-08, operator ruling). Lowered from 1.5.
#
# This is an ELIGIBILITY FLOOR, never a take-profit. Structure still determines
# the invalidation and liquidity still determines the objective; RR is only the
# ratio those two market-derived objects happen to produce. A 35-point
# structural stop against a legitimate 43-point liquidity target is 1.23R and
# now qualifies -- the target is not moved to 1.5R, and the stop is not shrunk
# to reach it. Neither boundary may be adjusted to manufacture the ratio.
MIN_QUALIFICATION_R = 1.0

#: The floor this replaced. Retained ONLY so telemetry can report which
#: opportunities exist solely because the floor moved. It gates nothing.
LEGACY_QUALIFICATION_R = 1.5

# Luna's prose -> the objective kind vocabulary the freshness gate understands.
# Deliberately narrow: an unrecognised phrase yields NO candidate rather than a
# guess, because guessing here would invent a target Luna never chose.
_DRAW_SYNONYMS = {
    "previous_day_high": ("previous day high", "prior day high", "pdh"),
    "previous_day_low": ("previous day low", "prior day low", "pdl"),
    "prior_session_high": ("prior session high", "previous session high"),
    "prior_session_low": ("prior session low", "previous session low"),
    "session_high": ("session high", "intraday high", "today's high", "todays high"),
    "session_low": ("session low", "intraday low", "today's low", "todays low"),
    "overnight_high": ("overnight high", "onh", "asia high"),
    "overnight_low": ("overnight low", "onl", "asia low"),
    "london_high": ("london high",),
    "london_low": ("london low",),
    "equal_highs": ("equal highs", "relative equal highs", "double top"),
    "equal_lows": ("equal lows", "relative equal lows", "double bottom"),
    "protected_swing": ("protected swing", "protected high", "protected low",
                        "swing high", "swing low"),
    "opposing_external_liquidity": ("external liquidity", "buy side liquidity",
                                    "sell side liquidity", "buyside", "sellside",
                                    "external range liquidity"),
    "imbalance_completion": ("imbalance", "fvg fill", "gap fill",
                             "imbalance completion", "inefficiency"),
    "expansion_objective": ("expansion objective", "measured move", "expansion target"),
    "opposing_range_boundary": ("range high", "range low", "range boundary",
                                "opposing range"),
    "htf_draw_on_liquidity": ("htf draw", "higher timeframe draw", "weekly high",
                              "weekly low", "monthly high", "monthly low"),
}


def _blank_trace() -> dict:
    from broker.candidate_decision_record import blank_trace
    return blank_trace()


#: reason -> (trace field to mark failed, status value). Only the stage that
#: actually declined is marked; every later stage stays None, which is how a
#: reader tells "was not reached" from "passed".
_TRACE_STAGE = {
    # PHASE 3 (2026-08-12): `qualification_rejected` and `direction_disagreement`
    # are gone from this file -- a mechanical opinion no longer refuses Terra, it
    # is recorded. Their mappings are removed with them rather than left behind
    # to imply a veto that no longer exists.
    "direction_invalid": ("qualification_result", "DIRECTION_INVALID"),
    "playbook_unauthorized": ("playbook_authorized", False),
    "tool_family_unauthorized": ("playbook_authorized", False),
    # STEP 7 — kept SEPARATE from playbook_authorized so the record can answer
    # "Terra selected an IFVG and it existed" vs "...and mechanics could not
    # find one" without reverse-engineering logs later.
    "tool_not_detected": ("tool_authorized", False),
    "tool_direction_mismatch": ("tool_authorized", False),
    "tool_not_execution_eligible": ("tool_authorized", False),
    "tool_selection_ambiguous": ("tool_authorized", False),
    "objective_id_missing": ("objective_resolution_status", "ID_MISSING"),
    "objective_missing": ("objective_resolution_status", "NO_OBJECTIVES_ENUMERATED"),
    "objective_id_unknown": ("objective_resolution_status", "ID_UNKNOWN"),
    "objective_unresolved": ("objective_resolution_status", "UNRESOLVED"),
    "objective_wrong_side": ("objective_resolution_status", "WRONG_SIDE"),
    "objective_off_tick": ("objective_resolution_status", "OFF_TICK"),
    # LUNA-SESSION-PO3-AUTHORITY-1. Its own stage: "the market is in a phase that
    # authorizes no new entry" is not an evidence defect, not a geometry defect
    # and not a Terra defect, and an audit must never have to guess which.
    "session_phase_blocks_entry": ("session_phase_authorized", False),
    "candle_gap_unrecovered": ("evidence_integrity", "CANDLE_GAP"),
    "derived_state_stale": ("evidence_integrity", "DERIVED_STATE_STALE"),
    "invalidation_missing": ("invalidation_resolution_status", "MISSING"),
    "invalidation_wrong_side": ("invalidation_resolution_status", "WRONG_SIDE"),
    "invalidation_off_tick": ("invalidation_resolution_status", "OFF_TICK"),
    "zero_risk": ("geometry_valid", False),
    "no_reference_price": ("geometry_valid", False),
    # EXEC-PRICE-FRESHNESS-1. Its own stage, not folded into geometry: the
    # geometry may be perfect and still unpriceable, and an audit must be able
    # to tell "the market offered nothing" from "we could not see the market".
    "execution_price_unavailable": ("evidence_integrity", "NO_EXECUTABLE_PRICE"),
    "contract_mismatch": ("geometry_valid", False),
    "reward_below_qualification": ("reward_risk_valid", False),
}


def _annotate_trace(trace: dict, reason: str, detail: str) -> None:
    """Record which stage declined. Never raises; evidence must not break trade
    logic by failing to describe it."""
    try:
        field, value = _TRACE_STAGE.get(reason, (None, None))
        if field:
            trace[field] = value
        if str(reason).startswith("objective"):
            trace["objective_rejection_reason"] = reason
            trace["objective_lookup_found"] = reason not in (
                "objective_id_missing", "objective_id_unknown",
                "objective_unresolved", "objective_missing")
        elif str(reason).startswith("invalidation"):
            trace["invalidation_rejection_reason"] = reason
        elif field == "qualification_result":
            trace["qualification_reason"] = str(detail)[:200]
        elif field == "geometry_valid":
            trace["geometry_reason"] = reason
    except Exception:  # noqa: BLE001  -- observability is never load-bearing
        pass


class NoCandidate(Exception):
    """No candidate is produced. `reason` says which rule declined.

    NOT an error type by default — a stand-down raises this too, and a
    stand-down is normal operation.
    """

    def __init__(self, reason: str, detail: str = "", stand_down: bool = False) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.stand_down = stand_down


@dataclass(frozen=True)
class StructuralInvalidation:
    """The exact price at which Luna's thesis is wrong, plus what makes it so."""
    price: float
    structure_type: str
    structure_identity: str
    evidence_source: str
    evidence_timestamp: str

    def evidence(self) -> dict:
        return {"price": self.price, "structure_type": self.structure_type,
                "structure_identity": self.structure_identity,
                "evidence_source": self.evidence_source,
                "evidence_timestamp": self.evidence_timestamp}


def _digest(obj) -> str:
    """Order-independent digest. Dict insertion order must not change identity."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).strip()


# ── mechanical enumeration ────────────────────────────────────────────────────
#: Deterministic short IDs the Brain selects by. BUILD-CANONICAL-EXTERNAL-BRAIN-
#: EXECUTION-BRIDGE (2026-08-07): PROD-20260807 proved the catalog below was
#: already correct and already contained every level Terra wanted -- 29452.50
#: was enumerated on all 23 propose-entry scans -- but the catalog was computed
#: AFTER the Brain call and never shown to it. The join key was prose:
#: `classify_draw` mapped narrative text to an objective KIND, and returned None
#: on 17 of 23 proposals because rich prose naming several levels hits two
#: synonym sets at once. Worse, when a kind DID resolve, the price Terra named
#: was ignored -- selection was kind + side only, so at 09:47:03 Terra named
#: 29493.25 and the resolver bound 29452.50.
#:
#: The fix is not fuzzier parsing. It is to stop using prose as the execution
#: join key: publish this catalog to the Brain, have it return an ID, and bind
#: by identity.
_OBJECTIVE_ID_PREFIX = {
    "opposing_external_liquidity": "OBJ_LIQ",
    "protected_swing": "OBJ_PS",
}


def objective_id(objective: dict, index: int) -> str:
    """Stable within a snapshot, derived from the objective's own identity."""
    prefix = _OBJECTIVE_ID_PREFIX.get(objective.get("kind"), "OBJ")
    side = (objective.get("supporting_evidence") or {}).get("side")
    tag = {"buy_side": "BSL", "sell_side": "SSL"}.get(side, "")
    return f"{prefix}{'_' + tag if tag else ''}_{index}"


#: WHAT AN OBJECTIVE ROW'S RELATIVE FIELDS WERE MEASURED FROM.
#:
#: `settled_market_truth` is the newest SETTLED close published as
#: `market.current_price` with `market.settled_price_basis` -- structural market
#: truth, explicitly NOT an executable price (`brain_input._settled_price`).
#: `caller_supplied_reference` is any other reference the caller passed, and
#: claims nothing about its provenance: the candidate producer rebuilds this
#: catalog against the FRESH EXECUTABLE quote before binding, and a row built
#: that way must not describe itself as settled truth.
REFERENCE_SETTLED_MARKET_TRUTH = "settled_market_truth"
REFERENCE_CALLER_SUPPLIED = "caller_supplied_reference"


def authorized_objective_catalog(snapshot: dict, brain_input: dict,
                                 reference_price: float = None) -> list:
    """The catalog PUBLISHED TO THE BRAIN, with stable selectable IDs.

    Same producer, same levels, same doctrine as `enumerate_objectives` -- this
    adds identity and directional validity so the Brain can point at one.

    EVERY REFERENCE-RELATIVE FIELD NAMES ITS OWN REFERENCE (2026-09-02).
    `side`, `valid_for` and the intervening-structure block are all measured
    FROM a reference price, and the row used to carry them while saying nothing
    about what that reference was. Two different references legitimately reach
    this function: `narrative_brain` publishes the Brain's catalog from
    `market.current_price` (settled structural truth), and
    `_objective_selected` REBUILDS it from the fresh executable quote before
    binding the id the Brain chose. Those authorities are deliberately separate
    and are not being collapsed -- but a row that says `valid_for: bearish`
    without saying "relative to 29110.00 settled_close:1m" implies a currency
    the producing mechanism never proved. PROD-20260902 measured the two
    references 7.00 points apart in the same scan.

    The semantics are DERIVED, never asserted: a reference that is numerically
    the published settled price IS the settled price, whatever the caller
    intended; anything else is labelled as merely caller-supplied.
    """
    mk = (brain_input or {}).get("market") or {}
    settled = mk.get("current_price")
    ref_basis, ref_semantics = None, REFERENCE_CALLER_SUPPLIED
    try:
        if (reference_price is not None and settled is not None
                and float(reference_price) == float(settled)):
            ref_basis = mk.get("settled_price_basis")
            ref_semantics = REFERENCE_SETTLED_MARKET_TRUTH
    except (TypeError, ValueError):
        ref_basis, ref_semantics = None, REFERENCE_CALLER_SUPPLIED
    catalog = []
    for i, o in enumerate(enumerate_objectives(snapshot, brain_input), start=1):
        entry = dict(o)
        entry["objective_id"] = objective_id(o, i)
        if reference_price:
            entry["side"] = ("above_market" if o["price"] > reference_price
                             else "below_market")
            entry["valid_for"] = ("bullish" if o["price"] > reference_price
                                  else "bearish")
            entry.update(_intervening_protected_levels(
                brain_input, reference_price, o["price"]))
            # Stamped AFTER the fields it describes, so a row can never carry
            # reference-relative semantics without the reference itself.
            entry["reference_price"] = float(reference_price)
            entry["reference_basis"] = ref_basis
            entry["reference_semantics"] = ref_semantics
            entry["distance_from_reference"] = round(
                abs(float(o["price"]) - float(reference_price)), 6)
            entry["executable_revalidation_required"] = True
        catalog.append(entry)
    return catalog


def _intervening_protected_levels(brain_input: dict, reference_price,
                                  objective_price) -> dict:
    """Does an INTACT protected level stand between price and this objective?

    FVG-LOCATION-AND-PATH-EVIDENCE-1 (2026-08-24). `enumerate_objectives`
    publishes every level flat -- no ordering, no relationship between them.
    On 2026-08-24 at 10:52 it offered, from an entry of 29092.25, BOTH

        OBJ_PS_4       protected_swing              28979.50   (intact)
        OBJ_LIQ_SSL_2  opposing_external_liquidity  28947.75

    with nothing recording that reaching the second REQUIRES trading through
    the first. Luna named 28979.50 in prose as "the nearer protected-low
    reference", wrote that price would only be retracing toward it "until
    authoritative acceptance below it occurs", and then selected 28947.75 --
    lifting nominal reward-to-risk from 6.264R to 8.028R, +28.2%.

    PRESENCE IS LIVENESS. `ProtectedSwingTracker` pops a level the moment a
    close accepts through it, so every level still in `by_timeframe` is intact
    by construction. That is the only "intact" claim made here.

    THIS PUBLISHES TRUTH AND NOTHING ELSE. No objective is rejected, reordered,
    clipped or preferred; reward-to-risk law is untouched; acceptance is not
    required before an objective may be published or chosen. Whether trading
    through a defended level is worth it remains a discretionary judgement --
    it simply stops being an invisible one.
    """
    out = {"protected_level_between_entry_and_target": False,
           "intervening_protected_levels": []}
    try:
        ref, tgt = float(reference_price), float(objective_price)
        bt = ((brain_input or {}).get("protected_swings") or {}).get("by_timeframe") or {}
        lo, hi = (tgt, ref) if tgt < ref else (ref, tgt)
        rows = []
        for side in ("highs", "lows"):
            for tf, rec in (bt.get(side) or {}).items():
                if not isinstance(rec, dict) or rec.get("level") is None:
                    continue
                lvl = float(rec["level"])
                # STRICTLY between: a level AT the objective is that objective,
                # not something standing in front of it.
                if not (lo < lvl < hi):
                    continue
                rows.append({"level": round(lvl, 4), "timeframe": tf,
                             "role": rec.get("role"), "basis": rec.get("basis"),
                             "swing_id": rec.get("swing_id"),
                             "registered_at": rec.get("registered_at"),
                             # Registered means not yet accepted through.
                             "status": "intact_no_acceptance_through"})
        rows.sort(key=lambda r: abs(r["level"] - ref))
        out["intervening_protected_levels"] = rows
        out["protected_level_between_entry_and_target"] = bool(rows)
        if rows:
            out["nearest_intervening_protected_level"] = rows[0]["level"]
    except (TypeError, ValueError):
        return out
    return out


#: ROADMAP STEP 7 (2026-08-12) — the directional-prefix contract, single owner.
#: `toolbox` names instances directionally (`bullish_ifvg`); Terra names a
#: FAMILY (`ifvg`). Canonicalisation is EXACT: strip a known directional prefix,
#: nothing else. No substring, fuzzy, startswith-guess, edit-distance or semantic
#: matching -- `unicorn_block` must match nothing, and `order_block` must never
#: pass because some other bullish tool happens to exist.
_TOOL_DIRECTION_PREFIX = {"bullish_": "bullish", "bearish_": "bearish"}


#: STEP 4B.12 §7 UNIT 7 — why `ifvg` may be seen but not traded. Named so a
#: refusal is self-explaining in the trace, the journal and the operator log,
#: and so re-enabling it later is a deliberate act against a named condition
#: rather than the quiet deletion of a flag.
IFVG_QUARANTINE_REASON = "ifvg_occurrence_semantics_uncertified"


def _family_of(tool_name) -> str:
    """Family of a directional tool name, for exact-equality comparisons."""
    return canonical_tool_family(tool_name)[0] or ""


def canonical_tool_family(tool_name) -> tuple:
    """('ifvg', 'bullish') from 'bullish_ifvg'. Direction is None when the
    instance carries no directional prefix. Never raises."""
    token = str(tool_name or "").strip().lower()
    for prefix, direction in _TOOL_DIRECTION_PREFIX.items():
        if token.startswith(prefix):
            return token[len(prefix):], direction
    return token, None


def authorized_tool_catalog(snapshot: dict) -> list:
    """Execution expressions the DETERMINISTIC toolbox actually detected.

    ROADMAP STEP 7. Terra's `recommended_tool_family` was free text: the
    2026-08-12 preflight proved that `order_block` (never detected),
    `rejection_block` (detected but `execution_eligible=False`) and even
    `unicorn_block` (not vocabulary at all) were all ACCEPTED, and could ride a
    separately-valid protected-swing invalidation to a real bracket. The
    producer already publishes an authorised catalog for the two other facts
    Terra selects -- invalidations and objectives -- and resolves both by ID.
    Tools had no such catalog. This is it.

    It is NOT "tools Terra should pick". It is "expressions deterministic
    evidence proves exist in this snapshot". Detection comes ONLY from the
    toolbox output already on the snapshot -- nothing is re-detected here.

    PROVISIONAL ENTRIES ARE PUBLISHED, carrying `execution_eligible: False`.
    That is the CONTINUITY-2F witness/authority split: Terra keeps seeing the
    market expression forming, while mechanics refuse to execute it. Blinding
    the Brain to a real opportunity would be a different defect.

    An EMPTY catalog is a legitimate market result and is never manufactured.
    """
    out = []
    tb = (snapshot or {}).get("toolbox") or {}
    # STEP 4B.12 §6 UNIT 6 — PLAIN FVG IS PUBLISHED PER EXACT OCCURRENCE.
    #
    # `tool_candidates` is one entry per TOOL NAME (the compatibility shape), so
    # several lawful FVG occurrences would arrive as a single row carrying the
    # family view's geometry and the family view's eligibility. The resolver
    # below has to be able to COUNT the real alternatives to know whether
    # Terra's family token identifies one market object or several, and a
    # collapsed row makes three lawful occurrences look like one -- or, when the
    # family view is ambiguous, like none.
    #
    # The exact instances are already published on the snapshot by
    # `run_toolbox`; they are read here rather than re-detected.
    for inst in tb.get("tool_instances") or []:
        if not isinstance(inst, dict) or inst.get("family") != "fvg":
            continue
        if not inst.get("occurrence_id"):
            continue
        out.append({
            "tool": str(inst.get("tool")).lower(),
            "tool_family": "fvg",
            "direction": inst.get("direction"),
            "source_tf": inst.get("source_tf"),
            "level_type": "fvg_zone",
            "occurrence_id": inst["occurrence_id"],
            "zone_low": inst.get("zone_low"),
            "zone_high": inst.get("zone_high"),
            "execution_eligible": inst.get("execution_eligible") is True,
            "temporal_class": inst.get("temporal_class"),
            "execution_ineligible_reason": inst.get("execution_ineligible_reason"),
            # FVG-LOCATION-AND-PATH-EVIDENCE-1 — WHERE THIS GAP IS.
            **_fvg_location_facts(inst, snapshot),
        })
    #: Whether this snapshot could supply occurrence-exact FVG instances at all.
    #: An older archive or a fixture predating Unit 6 carries `tool_candidates`
    #: and no `tool_instances`; it stays READABLE through the compatibility row
    #: below rather than silently losing its FVG entry, which is the same
    #: "an older archive stays readable without becoming authoritative" policy
    #: this function already applies to eligibility.
    _fvg_exact = any(isinstance(i, dict) and i.get("family") == "fvg"
                     and i.get("occurrence_id")
                     for i in (tb.get("tool_instances") or []))
    for cand in tb.get("tool_candidates") or []:
        if _fvg_exact and _family_of(cand.get("tool")) == "fvg":
            continue          # already published, occurrence-exactly, above
        #: READABLE IS NOT AUTHORITATIVE. A snapshot predating Unit 6 has an FVG
        #: compatibility row and no exact occurrence behind it, so it cannot say
        #: WHICH gap it means. Publishing it keeps the archive inspectable;
        #: letting it through the Option-2 resolver would let it pass as a
        #: uniquely-identified singleton when nothing identified it at all.
        #: Its occurrence_id is not reconstructed from price, timeframe, list
        #: position or tool_id -- an identity that has to be guessed is not one.
        _legacy_fvg = (not _fvg_exact) and _family_of(cand.get("tool")) == "fvg"
        if not isinstance(cand, dict) or not cand.get("tool"):
            continue                      # malformed entry is not evidence
        pl = cand.get("price_level") or {}
        family, direction = canonical_tool_family(cand.get("tool"))
        if family not in CONCRETE_TOOL_FAMILIES:
            continue                      # not an approved expression
        #: STEP 4B.12 §7 UNIT 7 — IFVG IS OBSERVABLE, NOT EXECUTABLE.
        #:
        #: The object published as `ifvg` cannot currently prove it is an
        #: inverse fair value gap. Measured on the venue tape: its existence and
        #: side come from the liquidity-sweep machinery, while its GEOMETRY is
        #: whatever `_find_fvg` returns as the newest ordinary gap of the
        #: requested direction -- and on 202 of 215 deliveries that gap had
        #: never closed through its far boundary at all, most having formed on
        #: the current bar and never been touched. Nothing in the tree links the
        #: two facts: there is no source-occurrence relation, no inversion
        #: event, no canonical identity, no lifecycle, and readiness scores
        #: snapshot context rather than any particular gap.
        #:
        #: 231 execution-eligible entries across 197 of 250 scans were flowing
        #: through that. The repair is NOT to invent an inverse-FVG ontology
        #: under release pressure -- it is to stop an object that cannot say
        #: what it is from authorising a trade, while leaving every trace of it
        #: visible. OBSERVABLE != EXECUTABLE.
        #:
        #: EXACT FAMILY EQUALITY. `canonical_tool_family` already strips the
        #: directional prefix, so this matches `ifvg` and never `fvg`,
        #: `opening_fvg`, or any other name that merely contains those letters.
        #:
        #: `preferred_tool` is deliberately NOT touched: it is testimony, it
        #: carries no production execution authority, it is not serialized into
        #: brain_input, and this resolver already refuses to repair anything
        #: with it. Suppressing it would widen the change for no safety gain.
        _quarantined = family == "ifvg"
        out.append({
            "tool": str(cand.get("tool")).lower(),
            "tool_family": family,
            "direction": direction or pl.get("direction"),
            "source_tf": pl.get("source_tf"),
            "level_type": pl.get("level_type"),
            # FAIL CLOSED: only an explicit True is execution authority. Absent,
            # None or unknown eligibility is NOT permission -- an older archive
            # stays readable without becoming authoritative.
            # COMPOSITE authority. Quarantine is an ADDITIONAL veto, never a
            # substitute for one that already fired.
            "execution_eligible": (pl.get("execution_eligible") is True
                                   and not _legacy_fvg and not _quarantined),
            "temporal_class": pl.get("temporal_class"),
            # THE QUARANTINE SCAR, ADDITIVE. Carried in its OWN fields so it
            # cannot paint over a defect the row already had. Of the 260 IFVG
            # rows on the venue tape 231 were executable and 29 were ALREADY
            # ineligible for an independent reason; writing the quarantine into
            # `execution_ineligible_reason` destroyed those 29 originals -- and
            # the loss was self-demonstrating, because the first attempt to
            # measure "how many were executable before" could no longer tell a
            # quarantined row from a previously-broken one and reported 260
            # where the truth was 231. ONE EVIDENCE DEFECT MUST NEVER ERASE
            # ANOTHER.
            "execution_quarantined": bool(_quarantined),
            "execution_quarantine_reason": (
                IFVG_QUARANTINE_REASON if _quarantined else None),
            # UNDERLYING truth, preserved exactly as the toolbox reported it.
            "execution_ineligible_reason": (
                "occurrence_identity_unavailable_in_legacy_snapshot"
                if _legacy_fvg else pl.get("execution_ineligible_reason")),
            # TOOL-CATALOG-LOCATION-SEMANTICS-1 (2026-08-20). WHERE the tool is,
            # and WHY mechanics calls it ready. See `_tool_location_facts`.
            **_tool_location_facts(cand, pl),
        })
    out.extend(_po3_reversal_ob_rows(snapshot))
    anchored = _anchored_rejection_rows(snapshot)
    if anchored:
        # ONE EVENT, ONE OBJECT. Publishing an anchored block ALONGSIDE the
        # generic one puts two rows under a single tool name, and outside plain
        # FVG the resolver takes `eligible[0]` without refusing -- so the
        # generic, unanchored zone would silently win on list order. On the
        # 2026-08-20 tape that is a zone 100 points from the level it claims to
        # reject from.
        #
        # The anchored block SUPERSEDES the generic one for its direction: it is
        # the same family answering the same question with a structural referent
        # the generic scan does not have. The superseded row is not discarded --
        # it rides along under `superseded_generic` so the evidence survives.
        superseded = {r["direction"]: r for r in out
                      if r.get("tool_family") == "rejection_block"}
        out = [r for r in out if r.get("tool_family") != "rejection_block"
               or r.get("direction") not in {a["direction"] for a in anchored}]
        for row in anchored:
            prior = superseded.get(row["direction"])
            if prior is not None:
                row["superseded_generic"] = {
                    k: prior.get(k) for k in
                    ("level_type", "source_tf", "zone_low", "zone_high",
                     "execution_eligible", "execution_ineligible_reason")}
        out.extend(anchored)
    return out


#: PROTECTED-LEVEL-REJECTION-AGGRESSIVE-1 (2026-08-20). The anchored rejection
#: block is published as its OWN row rather than replacing the generic
#: `rejection_block` entry: they answer different questions and the generic scan
#: keeps its meaning. `level_type` names which one a reader is holding.
ANCHORED_REJECTION_LEVEL_TYPE = "protected_level_rejection_block"


def _leg_equilibrium_facts(block: dict) -> dict:
    """The CAUSAL leg's 0.50, serialised from the block that owns it.

    An earlier version recomputed this from `structure[tf].last_swing_high/low`
    -- whatever swing pair the structure engine happened to be holding, which is
    not necessarily the leg this reversal created. The detector is the only
    place that knows both true anchors (the protected manipulation extreme and
    the extreme the validating expansion reached), so the leg is built there and
    only carried here.

    Choosing a different swing because its midpoint clusters more prettily with
    the FVG or the block would be manufacturing confluence. Confluence is
    OBSERVED, not manufactured.
    """
    leg = (block or {}).get("retracement_leg")
    if not isinstance(leg, dict):
        return {"retracement_equilibrium": None,
                "retracement_equilibrium_reason":
                    (block or {}).get("retracement_leg_reason")}
    return {"retracement_equilibrium": leg.get("equilibrium_50"),
            "retracement_leg_low": leg.get("low"),
            "retracement_leg_high": leg.get("high"),
            "retracement_leg_low_source": leg.get("low_source"),
            "retracement_leg_high_source": leg.get("high_source"),
            "retracement_leg_expansion_from": leg.get("expansion_from"),
            "ote_low_pct": leg.get("ote_low_pct"),
            "ote_high_pct": leg.get("ote_high_pct")}


def _po3_reversal_ob_rows(snapshot: dict) -> list:
    """PO3 reversal order blocks, with their causal birth certificate.

    A DISTINCT family from `order_block`, which keeps its continuation meaning.
    The audit that preceded this found `order_block` authorized only under
    `trend_continuation` -- the playbook named for this very sequence,
    `manipulation_to_distribution`, could not express it. Authorizing the
    generic block there instead would have let ANY continuation block ride the
    reversal doctrine and made the causal requirement unenforceable.

    The row carries WHY it exists, not merely where it is: which liquidity side
    was manipulated, which run is being reclassified, and which expansion
    validated it. Before that expansion the detector publishes nothing at all --
    the manipulation leg is not yet an order block.

    Never raises.
    """
    rows = []
    try:
        from toolbox.price_levels import po3_reversal_order_block
        for direction in ("bullish", "bearish"):
            b = po3_reversal_order_block(snapshot or {}, direction)
            if not b.get("available"):
                continue
            rows.append({
                "tool": direction + "_po3_reversal_order_block",
                "tool_family": "po3_reversal_order_block",
                "direction": direction,
                "level_type": b.get("level_type"),
                "source_tf": b.get("source_tf"),
                "temporal_class": "settled",
                "execution_eligible": True,
                "execution_quarantined": False,
                "execution_quarantine_reason": None,
                "execution_ineligible_reason": None,
                "zone_low": b.get("zone_low"),
                "zone_high": b.get("zone_high"),
                "mean_threshold": b.get("mean_threshold"),
                "invalidation_level": b.get("invalidation_level"),
                # GEOMETRY fact, deliberately distinct from the invalidation
                # authority above: the run's own extreme is not the protected
                # swing, because the swing candle is not a member of the run.
                "run_extreme": b.get("run_extreme"),
                "protected_swing_id": b.get("protected_swing_id"),
                "protected_swing_role": b.get("protected_swing_role"),
                # ── the causal birth certificate ──────────────────────────
                "liquidity_side_taken": b.get("liquidity_side_taken"),
                "manipulation_sweep_tf": b.get("manipulation_sweep_tf"),
                "manipulation_sweep_direction": b.get("manipulation_sweep_direction"),
                "manipulation_reclaimed": b.get("manipulation_reclaimed"),
                "creating_run_start": b.get("creating_run_start"),
                "creating_run_end": b.get("creating_run_end"),
                "creating_run_length": b.get("creating_run_length"),
                "validation_timestamp": b.get("validation_timestamp"),
                "validation_basis": b.get("validation_basis"),
                "validation_close": b.get("validation_close"),
                # THE THIRD 50%. The operator's reversal entry reads three
                # INDEPENDENT equilibria in one retracement area: this block's
                # mean threshold, the FVG's midpoint (already published on every
                # zone), and the retracement leg's 0.50.
                #
                # They are published as three separate facts and never fused.
                # There is deliberately no confluence score, no equality test
                # and no proximity tolerance: operator ruling 2026-08-20 is that
                # this is a confluence POCKET, not a shared coordinate -- in the
                # illustrated trade the leg 0.50 and FVG midpoint nearly
                # coincide while the block's own MT sits deeper in the same
                # structure, and that is still the setup.
                #
                # NOT OTE. OTE proper remains 0.62-0.79 and is untouched.
                **_leg_equilibrium_facts(b),
            })
    except Exception:  # noqa: BLE001 -- evidence must never break the catalog
        return rows
    return rows


def _anchored_rejection_rows(snapshot: dict) -> list:
    """Rejection blocks that OWN a canonical protected level. Never raises.

    The generic detector takes `max(recent, key=upper_wick)` over five bars and
    is anchored to nothing, so on 2026-08-20 it published a 15m "bearish
    rejection block" at 29350.25-29367.75 while the level it was nominally
    rejecting from sat 100 points away at 29470.25. A big wick is not a
    rejection; a rejection is a failure AT something.

    These rows carry BOTH provenances -- the swing that owns the level and the
    finer candle that owns the geometry -- plus the mean threshold, which is the
    fact the operator reads to decide whether a retest actually failed. On
    2026-08-20 the 11:02 retest reached 29457.25 and died 2.125 points beneath
    a mean threshold of 29459.375.

    Eligibility is NOT asserted here. The block is a settled structural object;
    whether it is the trade remains Luna's, and whether an entry is affordable
    remains risk's.
    """
    rows = []
    try:
        from toolbox.price_levels import anchored_rejection_block
        for direction in ("bearish", "bullish"):
            b = anchored_rejection_block(snapshot or {}, direction)
            if not b.get("available"):
                continue
            rows.append({
                "tool": f"{direction}_rejection_block",
                "tool_family": "rejection_block",
                "direction": direction,
                "level_type": ANCHORED_REJECTION_LEVEL_TYPE,
                # The GEOMETRY's timeframe. `anchor_tf` carries the level's.
                "source_tf": b.get("rejection_block_tf"),
                "temporal_class": "settled",
                "execution_eligible": True,
                "execution_quarantined": False,
                "execution_quarantine_reason": None,
                "execution_ineligible_reason": None,
                "zone_low": b.get("zone_low"),
                "zone_high": b.get("zone_high"),
                "mean_threshold": b.get("mean_threshold"),
                "invalidation_level": b.get("invalidation_level"),
                "anchor_swing_id": b.get("anchor_swing_id"),
                "anchor_tf": b.get("anchor_tf"),
                "anchor_role": b.get("anchor_role"),
                "anchor_level": b.get("anchor_level"),
                "anchor_basis": b.get("anchor_basis"),
                "creating_candle_timestamp": b.get("creating_candle_timestamp"),
                "wick_extreme": b.get("wick_extreme"),
                "distance_to_anchor": b.get("distance_to_anchor"),
            })
    except Exception:  # noqa: BLE001 — evidence must never break the catalog
        return rows
    return rows


#: FVG-LOCATION-AND-PATH-EVIDENCE-1 (2026-08-24). Fractional position INSIDE a
#: zone, measured from the boundary price meets FIRST given the zone's own
#: direction. 0.0 = just made contact, 1.0 = standing at the far side.
#:
#: TELEMETRY, NOT A SIGNAL. No number here means "completed", "rejected",
#: "reversed", "shallow" or "deep", and nothing in the tree branches on it. It
#: exists because on 2026-08-24 at 10:52 the 15m bearish rebalance zone
#: 29038.00-29196.00 was published as `execution_eligible: true` with price at
#: 29092.25 -- 34% of the way in, with 103.75 points of zone still above -- and
#: the payload could say only that price was inside it. "Entered" and "worked
#: through" were the same fact.
def zone_penetration(direction: str, price, zone_low, zone_high) -> dict:
    """Where inside a zone price stands, and how much zone is left. Never raises.

    A BEARISH zone is approached from below, so its near boundary is
    `zone_low`; a BULLISH zone is approached from above and its near boundary
    is `zone_high`. Outside the zone every field is None -- an unpenetrated
    zone has no penetration, and 0.0 would be a different claim.
    """
    out = {"zone_width": None, "zone_penetration_pct": None,
           "distance_to_far_boundary": None, "penetration_near_boundary": None,
           "penetration_far_boundary": None}
    try:
        lo, hi, px = float(zone_low), float(zone_high), float(price)
    except (TypeError, ValueError):
        return out
    if hi < lo:
        lo, hi = hi, lo
    width = round(hi - lo, 4)
    out["zone_width"] = width
    if direction == "bearish":
        near, far = lo, hi
    elif direction == "bullish":
        near, far = hi, lo
    else:
        return out                     # no side, no near/far, no penetration
    out["penetration_near_boundary"] = round(near, 2)
    out["penetration_far_boundary"] = round(far, 2)
    if not (lo <= px <= hi):
        return out                     # not inside: penetration is not defined
    out["distance_to_far_boundary"] = round(abs(far - px), 2)
    if width > 0:
        out["zone_penetration_pct"] = round(abs(px - near) / width * 100.0, 2)
    return out


#: What an FVG row may say about its own location. `invalidated` and
#: `invalidation_level` are deliberately ABSENT: a plain FVG carries no
#: structural stop, and `_reanchor_location` would answer `invalidated: False`
#: from a level that does not exist -- an unbacked claim wearing a real field's
#: name. The occurrence's own authority already answers that question through
#: `execution_eligible` / `execution_ineligible_reason` and its lifecycle.
FVG_LOCATION_FIELDS = ("current_price", "price_relation", "entered_zone",
                       "distance_to_zone", "midpoint", "location_basis")


def _fvg_location_facts(inst: dict, snapshot: dict) -> dict:
    """WHERE this exact gap is, from the SAME authority every other tool uses.

    FVG-LOCATION-AND-PATH-EVIDENCE-1 (2026-08-24). `_tool_location_facts` reads
    a `price_level` dict, and the FVG branch above has none -- it publishes
    occurrence-exact instances straight from `tool_instances`, which carry
    geometry and lifecycle but never location. Measured on the 2026-08-24 venue
    tape: 0 of 12,629 plain-FVG catalog rows carried a location fact, against
    749 of 1,032 non-FVG rows. FVG was 92% of everything Luna was shown, and the
    only trade taken that session was an FVG -- entered 0.25 points off the
    lower boundary of a 20-point gap she could not see her position inside.

        `execution_eligible: true` IS NOT A LOCATION -- for gaps either.

    NO SECOND GEOMETRY SYSTEM. `_reanchor_location` stays the single owner of
    "where is price now": it is handed a zone and answers from the governed
    sided quote, fail-closed to `price_relation: unknown` when no lawful
    executable price exists. Nothing is recomputed here and no threshold is
    applied -- the caller is told where it stands and judges for itself.
    """
    facts = {}
    try:
        from toolbox.price_levels import _reanchor_location, _touch_tolerance
        zl, zh = inst.get("zone_low"), inst.get("zone_high")
        if zl is None or zh is None:
            return facts
        direction = inst.get("direction")
        tf = inst.get("source_tf")
        candles = (((snapshot or {}).get("timeframes") or {}).get(tf) or {}
                   ).get("recent_candles") or []
        zone = {"zone_low": zl, "zone_high": zh,
                "midpoint": round((float(zl) + float(zh)) / 2, 3),
                # The SAME adjacency rule the structural zones are built with,
                # derived from this gap's own timeframe.
                "_touch_tol": _touch_tolerance(candles)}
        _reanchor_location(zone, snapshot or {}, direction)
        for key in FVG_LOCATION_FIELDS:
            if key in zone:
                facts[key] = zone[key]
        facts.update(zone_penetration(direction, zone.get("current_price"),
                                      zl, zh))
    except Exception:  # noqa: BLE001 — evidence must never break the catalog
        return facts
    return facts


#: Fields the catalog carries so `execution_eligible` is not a context-free
#: boolean. Every one is OWNED UPSTREAM -- the catalog serialises, it never
#: recomputes, and it adds no judgement of its own.
TOOL_LOCATION_FIELDS = (
    "zone_low", "zone_high", "midpoint",
    "price_relation", "distance_to_zone", "entered_zone",
    "current_price", "settled_price", "location_basis",
    "invalidation_level", "invalidated",
)


def _tool_location_facts(cand: dict, pl: dict) -> dict:
    """WHERE a tool is and WHY it is ready. Pass-through, never recomputed.

    THE DEFECT THIS CLOSES. On 2026-08-20 at 11:02:10 the Brain was handed:

        {"tool": "bearish_ote_after_reclaim", "execution_eligible": true,
         "source_tf": "3m", "level_type": "ote_zone",
         "temporal_class": "settled"}

    and nothing else. The snapshot behind that row already held zone bounds
    29394.72-29412.74, the price relation, the distance, the invalidation level,
    `reasons: ["Sweep and reclaim confirmed", ...]` and
    `prerequisites_missing`. None of it survived into the catalog for any family
    except FVG.

    So Luna was asked to choose an execution expression while being told a tool
    was eligible and NOT WHERE IT WAS. Her 11:02 refusal -- "no qualified
    bearish entry geometry is currently established" -- was made with the map
    withheld: at the real price both eligible bearish zones sat 28 and 65 points
    BELOW the market, and she had no way to know it.

        `execution_eligible: true` IS NOT A LOCATION.

    `readiness_reasons` and `prerequisites_missing` are carried for the same
    reason. Mechanics had computed BOTH that the sweep-and-reclaim was confirmed
    AND that a prerequisite was still outstanding; publishing neither left the
    Brain to re-derive from raw candles the conclusion mechanics had already
    reached.

    Never raises: a row that cannot describe its location must still be
    delivered, and an absent fact is published as absent.
    """
    facts = {}
    try:
        for key in TOOL_LOCATION_FIELDS:
            if key in (pl or {}):
                facts[key] = pl.get(key)
        readiness = (cand or {}).get("readiness") or {}
        reasons = (cand or {}).get("reasons")
        if reasons:
            facts["readiness_reasons"] = list(reasons)
        missing = readiness.get("prerequisites_missing")
        # An EMPTY list is a real answer -- "nothing is missing" -- and is not
        # the same fact as "readiness was never computed". Both must be
        # distinguishable, so only a genuinely absent key is omitted.
        if missing is not None:
            facts["prerequisites_missing"] = list(missing)
        if readiness.get("next_status"):
            facts["readiness_next_status"] = readiness.get("next_status")
        if (cand or {}).get("tool_id"):
            facts["tool_id"] = cand.get("tool_id")
        # FVG-LOCATION-AND-PATH-EVIDENCE-1 — the same penetration telemetry the
        # FVG rows carry, so "inside a zone" means the same measurable thing
        # whichever family published it.
        facts.update(zone_penetration((pl or {}).get("direction"),
                                      facts.get("current_price"),
                                      facts.get("zone_low"),
                                      facts.get("zone_high")))
    except Exception:  # noqa: BLE001 — evidence must never break the catalog
        return facts
    return facts


def authorized_invalidation_catalog(brain_input: dict,
                                    flip_candidates: list = None) -> list:
    """Structural facts the Brain may select as invalidation, with IDs.

    The Brain never invents a stop level: it chooses a registered structure,
    and the producer still validates side and geometry.

    TWO FAMILIES, kept distinct (2026-08-11):

        protected_high / protected_low   a raided level that was rejected
        BROKEN_SUPPORT_FLIP / _RESISTANCE_FLIP   a level broken by a
                                         directional close, now on the other
                                         side of price

    Before the second family existed this function published at most two
    entries, both from `protected_swings`. On 2026-08-10 that meant the entire
    short side of a session was priced off one 15m protected high a median 88.75
    points away -- 1 of 53 inside the 40-point ceiling -- while the bot's own 5m
    block already knew support had broken 18 points overhead.

    This publishes FACTS, in whatever quantity legitimately exist. It does not
    rank by distance, does not choose, and does not drop a candidate for being
    too far away: the 40-point ceiling is a downstream permission, and applying
    it here would hide structural truth to make a trade possible.
    """
    prot = (brain_input.get("protected_swings") or {})
    out = []
    # MTF-RESTORATION (2026-08-11) — PER TIMEFRAME when the registry provides
    # it. The single-slot summary published one extreme level, so on
    # 2026-08-10 every bearish invalidation Terra ever saw was the 15m high,
    # 53 times, a median 88.75 points away. A 15m protected high and a 5m one
    # are different structural facts and both are now published, each carrying
    # its timeframe and role. Nothing is ranked by distance and nothing is
    # dropped for being far.
    by_tf = prot.get("by_timeframe") or {}
    seen_prices = set()
    for side, bucket in (("high", "highs"), ("low", "lows")):
        records = (by_tf.get(bucket) or {})
        for index, (tf, block) in enumerate(sorted(records.items()), start=1):
            if not isinstance(block, dict) or block.get("level") is None:
                continue
            price = float(block["level"])
            seen_prices.add((side, round(price, 4)))
            out.append({"invalidation_id": f"INV_P{side[0].upper()}_{tf}_{index}",
                        "type": f"protected_{side}",
                        "price": price,
                        "timeframe": tf,
                        "role": block.get("role"),
                        "swing_id": block.get("swing_id"),
                        "source": f"protected_swings.by_timeframe.{bucket}.{tf}",
                        "registered_at": block.get("registered_at"),
                        "basis": block.get("basis")})
    # The legacy summary fields still publish when the per-timeframe registry
    # is absent (older snapshots, replays), so nothing regresses.
    for side, key in (("high", "protected_high"), ("low", "protected_low")):
        block = prot.get(key)
        if not (isinstance(block, dict) and block.get("level") is not None):
            continue
        if (side, round(float(block["level"]), 4)) in seen_prices:
            continue
        out.append({"invalidation_id": f"INV_P{side[0].upper()}_1",
                    "type": f"protected_{side}",
                    "price": float(block["level"]),
                    "timeframe": block.get("timeframe"),
                    "role": block.get("role"),
                    "source": f"protected_swings.{key}",
                    "status": prot.get(f"{key}_status"),
                    "registered_at": block.get("timestamp")})
    for candidate in (flip_candidates
                      if flip_candidates is not None
                      else brain_input.get("structure_flips") or []):
        if isinstance(candidate, dict) and candidate.get("price") is not None:
            out.append(dict(candidate))
    return out


def resolve_objective_by_id(objective_id_value: str, catalog: list, *,
                            direction: str, reference_price: float) -> dict:
    """Bind the Brain's SELECTED objective id. No prose, no guessing.

    An unknown id is refused outright -- the Brain may only choose from what the
    deterministic layer published. Selection is not authorisation: side and
    price validity are still enforced here.
    """
    wanted = str(objective_id_value or "").strip()
    if not wanted:
        raise NoCandidate("objective_unresolved", "no objective_id supplied")
    match = [c for c in catalog if c.get("objective_id") == wanted]
    if not match:
        raise NoCandidate(
            "objective_id_unknown",
            f"objective_id {wanted!r} is not in the authorized catalog "
            f"{[c.get('objective_id') for c in catalog]}")
    chosen = match[0]
    on_side = (chosen["price"] > reference_price if direction == "bullish"
               else chosen["price"] < reference_price)
    if not on_side:
        raise NoCandidate(
            "objective_wrong_side",
            f"{wanted} at {chosen['price']} is on the wrong side of "
            f"{reference_price} for a {direction} thesis")
    return chosen


def enumerate_objectives(snapshot: dict, brain_input: dict) -> list:
    """Every liquidity objective the MECHANICAL layer can actually point to.

    Luna selects from these. The producer never adds one that the snapshot did
    not contain, so a candidate can never target a level that exists only in
    prose.
    """
    out = []
    liq = (brain_input.get("liquidity") or {})
    prot = (brain_input.get("protected_swings") or {})
    ts = str(brain_input.get("timestamp") or "")

    def add(kind, price, identity_suffix, source, evidence):
        try:
            px = float(price)
        except (TypeError, ValueError):
            return
        if px <= 0:
            return
        out.append({"kind": kind, "price": px,
                    "identity": f"{kind}:{identity_suffix}",
                    "source": source, "source_timestamp": ts,
                    "supporting_evidence": evidence})

    if liq.get("nearest_buy_side") is not None:
        add("opposing_external_liquidity", liq["nearest_buy_side"],
            f"buyside@{liq['nearest_buy_side']}", "liquidity.nearest_buy_side",
            {"side": "buy_side"})
    if liq.get("nearest_sell_side") is not None:
        add("opposing_external_liquidity", liq["nearest_sell_side"],
            f"sellside@{liq['nearest_sell_side']}", "liquidity.nearest_sell_side",
            {"side": "sell_side"})

    ph = prot.get("protected_high")
    if isinstance(ph, dict) and ph.get("level") is not None:
        add("protected_swing", ph["level"], f"high@{ph.get('timestamp', ts)}",
            "protected_swings.protected_high",
            {"status": prot.get("protected_high_status")})
    pl = prot.get("protected_low")
    if isinstance(pl, dict) and pl.get("level") is not None:
        add("protected_swing", pl["level"], f"low@{pl.get('timestamp', ts)}",
            "protected_swings.protected_low",
            {"status": prot.get("protected_low_status")})

    for extra in (snapshot.get("liquidity_objectives") or []):
        if isinstance(extra, dict) and extra.get("kind") in OBJECTIVE_KINDS:
            add(extra["kind"], extra.get("price"),
                extra.get("identity_suffix") or str(extra.get("price")),
                extra.get("source", "snapshot.liquidity_objectives"),
                extra.get("evidence") or {})
    return out


def classify_draw(active_draw: str) -> "str | None":
    """Map Luna's prose draw to one objective kind, or None if unrecognised."""
    text = _norm(active_draw)
    if not text:
        return None
    hits = {kind for kind, phrases in _DRAW_SYNONYMS.items()
            if any(p in text for p in phrases)}
    # Ambiguity is refusal, not a coin flip.
    return hits.pop() if len(hits) == 1 else None


def resolve_objective(active_draw: str, candidates: list, *, direction: str,
                      reference_price: float) -> dict:
    """Resolve Luna's named draw to exactly one enumerated objective."""
    kind = classify_draw(active_draw)
    if kind is None:
        raise NoCandidate("objective_unresolved",
                          f"Luna's draw {active_draw!r} does not map to exactly one "
                          f"authorized objective kind")
    matching = [c for c in candidates if c["kind"] == kind]
    if not matching:
        raise NoCandidate("objective_unresolved",
                          f"Luna named a {kind} draw but the snapshot enumerated none")
    # Only objectives on the profitable side can be the draw for this direction.
    side = [c for c in matching
            if (c["price"] > reference_price if direction == "bullish"
                else c["price"] < reference_price)]
    if not side:
        raise NoCandidate("objective_wrong_side",
                          f"every enumerated {kind} sits on the wrong side of "
                          f"{reference_price} for a {direction} thesis")
    if len(side) > 1:
        # NEVER pick the one with the best R. Ambiguity means Luna was not
        # specific enough to identify a single draw.
        raise NoCandidate(
            "objective_ambiguous",
            f"{len(side)} enumerated {kind} objectives match; refusing to choose "
            f"the one that flatters reward-to-risk")
    return side[0]


# ── the producer ──────────────────────────────────────────────────────────────
@dataclass
class CandidateProducer:
    """Turns one validated Luna pass into at most one CandidateSnapshot."""

    account_fingerprint: str
    contract: object                       # TopstepXContract
    ttl_seconds: float = DEFAULT_TTL_SECONDS
    min_r: float = MIN_QUALIFICATION_R
    active_candidate: "CandidateSnapshot | None" = None
    #: Legacy prose binding. FALSE in production. True only for replaying
    #: archives authored before the canonical catalog existed.
    allow_prose_objective_fallback: bool = False
    _superseded: list = field(default_factory=list)
    #: Stage-by-stage record of the LAST produce() call. Written only; the
    #: producer never reads it back, so evidence cannot become authority.
    last_decision_trace: dict = field(default_factory=dict)

    @staticmethod
    def _assert_session_phase_permits_entry(snapshot: dict) -> dict:
        """THE ACCUMULATION BLOCK. Upstream of playbook, tool, geometry and risk.

        LUNA-SESSION-PO3-AUTHORITY-1. This is the first thing `produce` asks,
        before Terra's thesis is even read, because the question it answers is
        about the market and not about the proposal: "is this a phase in which a
        NEW position may be opened at all?"

        Position MANAGEMENT is untouched -- `manage_open_position` runs before
        this method is ever reached, and emergency/flatten authority never passes
        through here. This declines to OPEN exposure; it can never decline to
        protect it.

        Absence of a session_po3 block is permissive on purpose. A snapshot built
        by a caller that predates this unit must not be silently converted into a
        stand-down: the phase authority blocks on PROVEN accumulation, never on
        its own absence.
        """
        block = (snapshot or {}).get("session_po3")
        if not isinstance(block, dict) or not block.get("phase"):
            return {"phase": None, "authorized": True, "reason": "no session_po3 block"}
        if block.get("new_entry_allowed", True):
            return {"phase": block.get("phase"), "authorized": True, "reason": None}
        raise NoCandidate(
            "session_phase_blocks_entry",
            f"session PO3 phase {block.get('phase')}: "
            f"{block.get('block_reason') or 'new entry not authorized'}",
            stand_down=True)

    def produce(self, *, brain_result: dict, brain_input: dict, snapshot: dict,
                qualification: dict, engine_inventory: dict,
                snapshot_id: str, market_data_timestamp: str,
                latest_closed_bar_timestamp: str, in_window: bool = True,
                ai_state: str = "AI_OK", now: datetime = None) -> CandidateSnapshot:
        now = now or datetime.now(timezone.utc)

        # EVIDENCE, NOT AUTHORITY. The trace records which stage a proposal
        # died at; nothing below ever reads it back. PROD-20260807 had to be
        # reconstructed by hand precisely because this did not exist.
        trace = _blank_trace()
        self.last_decision_trace = trace
        _p = brain_result.get("parsed") or {}
        trace["requested_objective_id"] = _p.get("objective_id")
        trace["requested_invalidation_id"] = _p.get("invalidation_id")
        # OBSERVABILITY (2026-08-11). These were populated only AFTER the
        # action check, so all 108 stand-down scans of 2026-08-10 recorded
        # None and the deterministic-vs-Terra comparison was unanswerable for
        # the whole session. Whatever is knowable BEFORE that gate is now
        # recorded regardless of how the scan ends.
        _q = qualification or {}
        _qdir = _q.get("direction") or _q.get("qualified_direction")
        _bdir = _p.get("narrative_direction")
        trace["brain_direction"] = _bdir
        trace["deterministic_direction"] = _qdir
        if _qdir and _bdir:
            trace["direction_agreement"] = (str(_qdir) == str(_bdir))
        _mtf = ((snapshot or {}).get("mtf_market_state") or {}).get("synthesis") or {}
        trace["mtf_alignment_state"] = _mtf.get("alignment_state")
        trace["mtf_conflicts"] = _mtf.get("conflicts")
        trace["context_timeframe_state"] = _mtf.get("context_state")
        trace["active_leg_timeframe_state"] = _mtf.get("active_leg_state")
        trace["transition_timeframe_state"] = _mtf.get("transition_state")
        trace["execution_timeframe_state"] = _mtf.get("execution_state")
        try:
            # PHASE AUTHORITY FIRST. Nothing below -- not Terra's thesis, not the
            # playbook, not a beautiful MSS/FVG/OTE, not Active Path direction --
            # may create a new entry inside an unresolved session accumulation.
            trace["session_phase"] = ((snapshot or {}).get("session_po3") or {}).get("phase")
            trace["session_phase_authorized"] = (
                self._assert_session_phase_permits_entry(snapshot)["authorized"])
            self._check_brain(brain_result, ai_state)
            parsed = brain_result.get("parsed") or {}
            self._assert_action_permits_entry(parsed)
            direction = self._direction(parsed, qualification, trace)
            # PHASE 3: `qualification_result` is now an OBSERVATION of what the
            # deterministic qualifier thought, not a gate Terra had to pass.
            trace["qualification_result"] = "OBSERVED"
            trace["qualification_reason"] = (qualification or {}).get("reason")
            playbook, tools = self._playbook(parsed, qualification, trace)
            trace["playbook_authorized"] = True

            # ROADMAP STEP 7 (2026-08-12) — SHOW ME THE TOOL.
            # A valid playbook, a valid invalidation and a valid objective are
            # each independent propositions and none of them proves the selected
            # execution expression EXISTS. Until this gate, it was never checked:
            # `unicorn_block` authorised. Terra interprets and selects; the
            # deterministic toolbox establishes what physically exists;
            # mechanics may VETO and may NEVER SUBSTITUTE.
            # TOOL-OCCURRENCE-SELECTION-1 — the return is CAPTURED, not discarded.
            # `tool_family: ["fvg"]` alone cannot answer "which gap authorized
            # this exposure" after the fact, and a market object that justified
            # real risk may not evaporate the moment it has done its job.
            selected_tool = self._assert_tool_detected(
                tools, direction, snapshot, trace,
                occurrence_id=parsed.get("recommended_tool_occurrence_id"))

            # CANDLE-CONTINUITY (2026-08-11). An unrepaired hole in the recent
            # tape may not authorise an entry. This is not caution about thin
            # data: `find_swings` confirms pivots against neighbours on BOTH
            # sides, so a gap can FABRICATE the very structure a thesis is
            # priced off. On 2026-08-11 twenty missing minutes hid the buy-side
            # manipulation through 29,800 and the Brain priced a stop off the
            # highest level its mutilated window contained.
            #
            # Placed with the other evidence-integrity refusals, before geometry
            # is resolved: a level derived from corrupted topology should never
            # reach the risk gate to be judged on its size.
            self._assert_candles_continuous(snapshot)
            self._assert_derived_state_current(snapshot)
            if not in_window:
                raise NoCandidate("window_closed", "outside the decision window")
            if str(snapshot.get("contract_id") or self.contract.id) != self.contract.id:
                raise NoCandidate("contract_mismatch", "snapshot is for another contract")

            reference_price = self._reference_price(brain_input, direction)
            invalidation = self._invalidation(parsed, snapshot, brain_input, direction,
                                              reference_price)
            trace.update(invalidation_lookup_found=True,
                         resolved_invalidation_id=invalidation.structure_identity,
                         resolved_invalidation_type=invalidation.structure_type,
                         resolved_invalidation_price=invalidation.price,
                         invalidation_side_valid=True, invalidation_fresh=True,
                         invalidation_resolution_status="RESOLVED")
            objective = self._objective(parsed, snapshot, brain_input, direction,
                                        reference_price, now)
            trace.update(geometry_valid=True, geometry_reason=None)

            rr = self._reward_to_risk(reference_price, invalidation.price,
                                      objective.price)
            # RR-FLOOR-1.0 counterfactual. Observational only: it records what
            # the retired 1.5 floor WOULD have done so Monday can say exactly how
            # many opportunities exist solely because the floor moved. It gates
            # nothing -- `reward_risk_valid` is still decided by self.min_r.
            trace.update(reward_risk=round(rr, 3), reward_risk_floor=self.min_r,
                         reward_risk_valid=rr >= self.min_r,
                         legacy_reward_risk_floor=LEGACY_QUALIFICATION_R,
                         legacy_floor_verdict=("WOULD_PASS"
                                               if rr >= LEGACY_QUALIFICATION_R
                                               else "WOULD_REJECT"),
                         eligible_only_because_floor_moved=bool(
                             rr >= self.min_r and rr < LEGACY_QUALIFICATION_R))
            if rr < self.min_r:
                raise NoCandidate(
                    "reward_below_qualification",
                    f"authentic geometry yields {rr:.2f}R, below the {self.min_r:.2f} floor. "
                    f"Neither boundary may be moved to improve it.")
        except NoCandidate as exc:
            _annotate_trace(trace, exc.reason, exc.detail)
            exc.decision_trace = dict(trace)
            raise

        cand = CandidateSnapshot(
            candidate_id="cand-" + _digest([snapshot_id, direction, objective.identity,
                                            invalidation.price, now.isoformat()]),
            snapshot_id=snapshot_id,
            direction=direction,
            entry_price=reference_price,
            invalidation_price=invalidation.price,
            objective=objective,
            contract_id=self.contract.id,
            account_fingerprint=self.account_fingerprint,
            created_at=now,
            narrative=str(parsed.get("market_story") or "")[:200],
            extras={
                "candidate_expires_at": (now + timedelta(seconds=self.ttl_seconds)).isoformat(),
                "contract_symbol": getattr(self.contract, "name", ""),
                "latest_closed_bar_timestamp": latest_closed_bar_timestamp,
                "market_data_timestamp": market_data_timestamp,
                "playbook": playbook,
                "tool_family": tools,
                # TOOL-OCCURRENCE-SELECTION-1 — WHICH market object authorized
                # this exposure. Taken from the VERIFIED match, never from the
                # raw response: this must mean "the occurrence mechanics proved",
                # not "a string Luna happened to send".
                #
                # PROVENANCE ONLY. The occurrence authorizes the expression; it
                # is NOT a price authority. `entry_price` remains the fresh
                # executable quote, the stop remains Luna's authored structural
                # invalidation, and the target remains the selected objective.
                # A zone boundary must never become the broker entry.
                "selected_tool_occurrence_id": (selected_tool or {}).get("occurrence_id"),
                "selected_tool": (selected_tool or {}).get("tool"),
                "selected_tool_source_tf": (selected_tool or {}).get("source_tf"),
                "entry_context": str(parsed.get("current_action") or ""),
                "entry_reference_price": reference_price,
                # EXEC-PRICE-FRESHNESS-1. WHAT the entry was priced from, with
                # its age — and the settled close alongside it, so a later audit
                # can measure the gap between market truth and executable price
                # instead of reconstructing it from candle archives the way
                # 2026-08-20 had to.
                "execution_price_evidence": (brain_input.get("market") or {}
                                             ).get("execution_price") or {},
                "settled_price_at_authorship": (brain_input.get("market") or {}
                                                ).get("current_price"),
                "settled_price_basis": (brain_input.get("market") or {}
                                        ).get("settled_price_basis"),
                "structural_invalidation": invalidation.evidence(),
                "liquidity_objective": self._objective_evidence(objective, parsed),
                "expected_reward_to_risk": round(rr, 3),
                "source": "live_llm",
                "model": brain_result.get("model"),
                "sovereign_conversion": True,
                "engine_inventory_digest": _digest(engine_inventory),
                "mechanical_evidence_digest": _digest(brain_input),
                "brain_response_digest": _digest(parsed),
            })

        self._supersede(cand)
        return cand

    # ── gates ─────────────────────────────────────────────────────────────────
    # Actions that explicitly decline to trade. A directional read carrying one
    # of these is a market NARRATIVE, never an entry.
    NON_ENTRY_ACTIONS = ("stand_down", "stand down", "no_trade", "no trade",
                         "do_not_trade", "flat", "wait", "hold_off")

    @classmethod
    def _assert_action_permits_entry(cls, parsed: dict) -> None:
        """A stand-down never becomes a candidate, whatever else it carries.

        SEPARATE-DIRECTION-FROM-ENTRY-ELIGIBILITY (2026-08-06): the prompt used
        to force any un-tradeable directional read to `conflicted`, so the
        producer got its safety indirectly -- a stand-down arrived with
        playbook 'none' and was refused as `playbook_unauthorized`. Direction and
        action are now separate, so a directional stand-down CAN legally name a
        family, and that incidental refusal would no longer fire. This gate is
        explicit and reads the action itself.
        """
        action = str((parsed or {}).get("current_action") or "").strip().lower()
        for token in cls.NON_ENTRY_ACTIONS:
            if action.startswith(token):
                raise NoCandidate(
                    "action_declines_entry",
                    f"current_action={action!r} declines entry; the direction is a "
                    f"market narrative, not a trade")

    @staticmethod
    def _check_brain(brain_result: dict, ai_state: str) -> None:
        r = brain_result or {}
        if ai_state in ("AI_TIMEOUT",):
            raise NoCandidate("brain_timeout", "Luna timed out")
        if ai_state in ("AI_STALE", "AI_SUPERSEDED"):
            raise NoCandidate("brain_superseded", f"brain guard reported {ai_state}")

        # ── TWO-BRAIN-HYBRID: a SECOND authority lane, not a hole in the first.
        #
        # The external-authoritative law below is unchanged and still governs
        # every thesis the external Brain authors. A deterministic thesis takes
        # a different route: it must arrive inside an envelope that PROVES, item
        # by item, that the runtime mode permits hybrid authority, that the
        # proposal is deterministic and complete, that it was not mutated during
        # adjudication, that adjudication happened, and that the derived
        # disposition allows continuation.
        #
        # Authority is never inferred from a missing `model` or from the string
        # "deterministic" -- inferring it would recreate exactly the bypass this
        # contract exists to prevent. No envelope means the old law applies.
        from ai_brain.two_brain import (HYBRID_ENVELOPE_KEY,
                                        authorized_hybrid_envelope)
        if r.get(HYBRID_ENVELOPE_KEY) is not None:
            verdict = authorized_hybrid_envelope(r)
            if not verdict["authorized"]:
                raise NoCandidate("hybrid_envelope_unauthorized", verdict["reason"])
            if not r.get("ok") or not r.get("parsed"):
                raise NoCandidate("brain_invalid", "no validated thesis in envelope")
            return
        if r.get("fallback_reason"):
            raise NoCandidate("fallback_not_authoritative",
                              f"thesis came from a fallback: {r['fallback_reason']}")
        if not r.get("ok") or not r.get("parsed"):
            raise NoCandidate("brain_invalid", "no validated Luna output")
        if r.get("model") != PRODUCTION_MODEL:
            raise NoCandidate("wrong_model",
                              f"thesis authored by {r.get('model')!r}, not {PRODUCTION_MODEL}")

    @staticmethod
    def _direction(parsed: dict, qualification: dict, trace: dict = None) -> str:
        """Terra owns direction. Mechanics may disagree, in writing.

        PHASE 3 AUTHORITY DEMOTION (2026-08-12). Two mechanical vetoes used to
        live here and both were opinions wearing a permission badge:

            direction_disagreement  -- refused because the deterministic
                                       qualifier preferred the other side
            qualification_rejected  -- refused because `qualified` was False

        Neither asserts a FACT about the market. "Mechanics did not resolve this
        side" is not "this side does not exist" -- and after Phase 2 we can
        measure the difference: on PROD-20260812-PM the mechanical direction
        disagreed with Terra on 60 of 81 scans while truthful inventory existed
        on her side for 54 of them.

        What still refuses here is Terra's OWN answer being unusable: a
        neutral/conflicted read is her stand-down, not ours. And nothing here
        weakens Step 7 -- her selected tool must still physically exist, on the
        right side, execution-eligible.
        """
        d = str(parsed.get("narrative_direction") or "").lower().strip()
        if d in ("neutral", "conflicted", ""):
            raise NoCandidate("stand_down", f"Luna direction is {d or 'absent'!r}",
                              stand_down=True)
        if d not in ("bullish", "bearish"):
            raise NoCandidate("direction_invalid", f"direction {d!r}")
        mech = str((qualification or {}).get("direction") or "").lower().strip()
        if trace is not None:
            trace["mechanical_direction_recommendation"] = mech or None
            trace["direction_agreement"] = (not mech) or (mech == d)
            trace["mechanical_qualification_observation"] = (
                "qualified" if (qualification or {}).get("qualified", True)
                else str((qualification or {}).get("reason") or "not qualified"))
        return d

    #: How far back a hole still poisons the read. Wide enough to cover the
    #: pivot-confirmation lookback every structural fact depends on; not the
    #: whole archive, because a hole in yesterday's tape is a fact about history
    #: rather than about the trade being considered now.
    CONTINUITY_HORIZON_MINUTES = 90

    @staticmethod
    def _assert_candles_continuous(snapshot: dict) -> None:
        """Refuse while the recent tape has an unrepaired hole.

        A missing report is NOT treated as continuous. Older snapshots and
        replays legitimately carry none, so absence of a report means the
        question was never asked -- and an unasked question cannot answer
        itself. That is the same doctrine `never_reached_venue` learned the hard
        way: absence of evidence is not evidence of absence.
        """
        report = snapshot.get("candle_continuity")
        if not isinstance(report, dict):
            return                      # never measured; nothing to assert on
        try:
            from data_feed.candle_continuity import material_gap
            blocking = material_gap(
                report,
                within_last=CandidateProducer.CONTINUITY_HORIZON_MINUTES)
        except Exception:  # noqa: BLE001 — an unreadable report fails closed
            blocking = True
        if blocking:
            # Describing the refusal must never be able to prevent it. A
            # malformed report is exactly the case where the message is hardest
            # to build and the refusal matters most.
            try:
                spans = [
                    f"{g.get('first_missing')}..{g.get('last_missing')} "
                    f"({g.get('missing_minutes')} min)"
                    for g in (report.get("gaps") or []) if isinstance(g, dict)]
                detail = "; ".join(spans) or "gap span unreadable"
            except Exception:  # noqa: BLE001
                detail = "gap span unreadable"
            raise NoCandidate(
                "candle_gap_unrecovered",
                f"the recent 1m tape has an unrepaired hole: {detail}")

    @staticmethod
    def _assert_derived_state_current(snapshot: dict) -> None:
        """Refuse while derived facts predate the history that exists now.

        Healthy candles are NOT sufficient. After a runtime repair the tape is
        continuous while the trackers still hold pre-repair facts, and a gate
        that only asked `continuous == True?` would recreate the same lie under
        a different flag. Normally the orchestrator rebuilds inside the same
        scan and these agree; a mismatch surviving to here means the rebuild
        FAILED, which is exactly when trading must stay refused.
        """
        state = snapshot.get("derived_state")
        if not isinstance(state, dict):
            return                      # never measured; replays carry none
        try:
            current = bool(state.get("current"))
            history = state.get("history_revision")
            derived = state.get("derived_revision")
        except Exception:  # noqa: BLE001
            current, history, derived = False, "?", "?"
        if not current:
            raise NoCandidate(
                "derived_state_stale",
                f"market history was revised to r{history} but derived facts "
                f"are from r{derived}; the rebuild has not proven current")

    @staticmethod
    def _playbook(parsed: dict, qualification: dict, trace: dict = None) -> tuple:
        """Terra owns playbook selection. Mechanics may recommend, in writing.

        PHASE 3. `authorized_playbooks` narrowed Terra's selectable set to
        whatever the deterministic classifier had already picked -- a
        recommendation enforced as a permission. Removed: a playbook Terra names
        is legal to NAME, and its factual prerequisites are proven downstream by
        Step 7 (the tool must exist, on her side, execution-eligible).

        Still refused: Terra naming no playbook or no tool at all. That is her
        own answer being empty, not mechanics overruling it.
        """
        pb = str(parsed.get("recommended_playbook_family") or "").strip().lower()
        tools = [str(t).strip().lower() for t in (parsed.get("recommended_tool_family") or [])
                 if str(t).strip()]
        neutral = {"", "none", "unknown", "confirmation_required", "n/a", "wait"}
        if pb in neutral:
            raise NoCandidate("playbook_unauthorized", f"playbook family {pb!r}")
        if not tools or all(t in neutral for t in tools):
            raise NoCandidate("tool_family_unauthorized", "no legal tool family")
        if trace is not None:
            allowed = (qualification or {}).get("authorized_playbooks") or []
            trace["mechanical_playbook_recommendation"] = list(allowed)
            trace["playbook_matches_recommendation"] = (
                (not allowed) or pb in {str(a).lower() for a in allowed})
        return pb, tools

    @staticmethod
    def _assert_tool_detected(tools: list, direction: str, snapshot: dict,
                              trace: dict = None, occurrence_id=None) -> dict:
        """Terra's selected expression must physically exist, on the right side,
        and be execution-eligible. Returns the matched catalog entry.

        ROADMAP STEP 7. Three propositions, each checked separately and each
        with its own refusal, so a stand-down is a RESULT rather than a null:

            TOOL_NOT_DETECTED             nothing of that family was detected
            TOOL_DIRECTION_MISMATCH       detected, but only on the other side
            TOOL_NOT_EXECUTION_ELIGIBLE   detected on the right side, but its
                                          geometry is provisional (CONTINUITY-2F)

        NO SUBSTITUTION, absolutely. A refusal is never repaired with
        `preferred_tool`, another detected family, the same family on the
        opposing side, a prior settled zone, a nearer level, a tighter stop or
        another timeframe's expression. Preferred is testimony; Terra owns
        selection; mechanics validate.
        """
        catalog = authorized_tool_catalog(snapshot)
        # COUNT FIRST, NORMALISE SECOND. `submitted` is what Terra actually
        # sent, untouched -- no stripping, no lowering, no dropping of blanks.
        submitted = list(tools or [])
        if trace is not None:
            trace["tool_selected"] = list(submitted)
            trace["tool_catalog"] = [e["tool"] for e in catalog]
        want = str(direction or "").strip().lower()

        # STEP 7 / 0A — EXACTLY ONE TOKEN, counted on what Terra ACTUALLY SENT.
        # `brain_prompt`: "recommended_tool_family MUST be a JSON ARRAY containing
        # exactly ONE tool family token ... Exactly one token, but always inside
        # an array." The list is a SCHEMA SHAPE, not a menu of alternatives.
        #
        # THREE earlier versions of this check were wrong, each softer than the
        # last, and every one of them was the same mistake:
        #   1. looped the list and returned the first eligible member, so
        #      ["rejection_block", "ifvg"] traded the IFVG;
        #   2. counted only CONCRETE families, so ["ifvg", "wait"] passed by
        #      quietly discarding the token mechanics did not like;
        #   3. filtered blank/whitespace elements before counting, so
        #      ["ifvg", ""] and ["   ", "ifvg"] collapsed to one and authorised.
        # All three are AI-output REPAIR. Mechanics may REJECT Terra's answer;
        # they may not SANITISE it into a different executable answer. The count
        # is therefore on the SUBMITTED ARRAY LENGTH -- two elements never
        # become one, whatever those elements contain.
        #
        # A sole neutral token ("none"/"wait"/"confirmation_required"/"n/a") is
        # refused one gate earlier by `_playbook`, which is the correct home for
        # the no-entry contract; `two_sided_watch` and a blank token survive that
        # gate and are refused here as not detected. What this rule adds is that
        # NO token may ride alongside another and vanish during validation.
        if len(submitted) != 1:
            if trace is not None:
                trace["tool_rejection_reason"] = "TOOL_SELECTION_AMBIGUOUS"
            raise NoCandidate(
                "tool_selection_ambiguous",
                f"TOOL_SELECTION_AMBIGUOUS: {submitted!r} — the contract is "
                f"exactly one tool family token. Mechanics will not choose "
                f"among, discard from, or repair Terra's selection.")

        raw = [str(submitted[0]).strip().lower()]
        for family in [canonical_tool_family(raw[0])[0]]:
            same_family = [e for e in catalog if e["tool_family"] == family]
            if not same_family:
                continue
            # STEP 7 / 0B — an EXPLICIT match, never a permissive one. This
            # previously also accepted an entry whose `direction` was missing or
            # empty, which would have made one expression compatible with BOTH
            # sides. Production always supplies a direction (the toolbox names
            # instances `bullish_`/`bearish_` and `_make_zone`/`_no_zone` both
            # set it), so this costs nothing today -- but absence of directional
            # evidence is not evidence of compatibility, and an archive or a
            # malformed entry must not become universal permission.
            on_side = [e for e in same_family
                       if str(e.get("direction") or "").strip().lower() == want]
            if not on_side:
                if trace is not None:
                    trace["tool_detected"] = True
                    trace["tool_rejection_reason"] = "TOOL_DIRECTION_MISMATCH"
                raise NoCandidate(
                    "tool_direction_mismatch",
                    f"TOOL_DIRECTION_MISMATCH: {family!r} was detected, but only "
                    f"as {sorted({e['direction'] for e in same_family})} — a "
                    f"{want} trade cannot be expressed by it")
            eligible = [e for e in on_side if e["execution_eligible"]]
            if not eligible:
                # EVERY authority that fired, not the first one found. A row can
                # be refused for its own defect AND be quarantined, and a
                # refusal that named only one of them would be the erasure this
                # catalog was just repaired to prevent -- an operator reading
                # "provisional geometry" would never learn the family is
                # withheld outright.
                quarantine = sorted({e["execution_quarantine_reason"]
                                     for e in on_side
                                     if e.get("execution_quarantined")})
                underlying = sorted({e["execution_ineligible_reason"]
                                     for e in on_side
                                     if e.get("execution_ineligible_reason")})
                reason = "; ".join(quarantine + underlying) or "geometry is not settled"
                if trace is not None:
                    trace["tool_detected"] = True
                    trace["tool_execution_eligible"] = False
                    trace["tool_rejection_reason"] = "TOOL_NOT_EXECUTION_ELIGIBLE"
                raise NoCandidate(
                    "tool_not_execution_eligible",
                    f"TOOL_NOT_EXECUTION_ELIGIBLE: {family!r} was detected but "
                    f"cannot author execution geometry — {reason}")
            # STEP 4B.12 §6 UNIT 6 — CARDINALITY BEFORE EXTRACTION.
            #
            # `eligible[0]` was the last silent mechanical choice on this path.
            # The refusal three lines above already states the doctrine -- "the
            # contract is exactly one tool family token. Mechanics will not
            # choose among, discard from, or repair Terra's selection" -- and
            # then a list index chose among them anyway.
            #
            # Plain FVG can now present SEVERAL exact occurrences under one
            # family token, because Terra's contract names a family and a market
            # can hold more than one lawful gap. When the family token resolves
            # to exactly one occurrence there is nothing to choose and taking it
            # is EXTRACTION. When it resolves to several, mechanics refuses --
            # it does not rank, sort, prefer the newest, or take the first.
            #
            # Scoped to plain FVG by exact family equality: no other family's
            # instance contract is touched, and `ifvg`/`opening_fvg` are not
            # matched by a substring of their names.
            # TOOL-OCCURRENCE-SELECTION-1 — THE JOIN KEY, NOT A RANKING.
            #
            # `eligible` is already filtered to this family, this direction and
            # execution-eligible only, so matching an id INSIDE it inherits every
            # one of those checks: a wrong-family, wrong-direction, retired,
            # quarantined or nonexistent id simply is not present and fails
            # closed. Contract scope rides inside the id string itself.
            #
            # Mechanics VERIFIES the object Luna named. It never substitutes
            # another, never falls back to the first row, and never ranks the
            # alternatives -- the refusal below already states that doctrine and
            # a silent fallback here would contradict it.
            # SCOPED TO PLAIN FVG BY EXACT FAMILY EQUALITY. Two defects lived in
            # an ungated version of this branch, both proven behaviourally:
            #
            #   non-FVG family + any non-null id  -> no row could match (every
            #     non-FVG catalog row carries occurrence_id None), so a lawful
            #     rejection_block/breaker trade was REFUSED. A prompt violation
            #     must not kill a family this field has no authority over.
            #
            #   non-FVG family + the literal "None" -> `str(None) == "None"`
            #     matched every such row, and with one eligible row it SELECTED
            #     it. A hallucinated value acquiring selection authority is the
            #     precise opposite of fail-closed.
            #
            # Outside plain FVG the field is now observationally irrelevant and
            # those families keep their exact pre-unit resolution semantics.
            wanted = str(occurrence_id or "").strip()
            if family == "fvg" and wanted:
                # A row with NO identity may never be selected. `None` is not a
                # name, and it must never be normalised into a selectable one.
                named = [e for e in eligible
                         if e.get("occurrence_id") is not None
                         and str(e["occurrence_id"]) == wanted]
                if len(named) != 1:
                    if trace is not None:
                        trace["tool_detected"] = True
                        trace["tool_requested_occurrence_id"] = wanted
                        trace["tool_rejection_reason"] = "TOOL_OCCURRENCE_UNKNOWN"
                    raise NoCandidate(
                        "tool_occurrence_unknown",
                        f"TOOL_OCCURRENCE_UNKNOWN: {wanted!r} is not an "
                        f"execution-eligible {want} {family!r} occurrence in this "
                        f"snapshot "
                        f"({sorted(str(e.get('occurrence_id')) for e in eligible)}). "
                        f"Mechanics will not substitute another occurrence.")
                match = named[0]
                if trace is not None:
                    trace["tool_detected"] = True
                    trace["tool_execution_eligible"] = True
                    trace["tool_requested_occurrence_id"] = wanted
                    trace["tool_matched"] = match["tool"]
                    trace["tool_matched_occurrence_id"] = str(match.get("occurrence_id"))
                    trace["tool_matched_source_tf"] = match.get("source_tf")
                    trace["tool_rejection_reason"] = None
                return match

            if family == "fvg" and len(eligible) > 1:
                ids = sorted(str(e.get("occurrence_id")) for e in eligible)
                if trace is not None:
                    trace["tool_detected"] = True
                    trace["tool_execution_eligible"] = True
                    trace["tool_rejection_reason"] = "TOOL_OCCURRENCE_AMBIGUOUS"
                    trace["tool_eligible_occurrences"] = len(eligible)
                raise NoCandidate(
                    "tool_occurrence_ambiguous",
                    f"TOOL_OCCURRENCE_AMBIGUOUS: {family!r} {want} resolves to "
                    f"{len(eligible)} execution-eligible occurrences "
                    f"({', '.join(ids)}) on "
                    f"{sorted({str(e.get('source_tf')) for e in eligible})}. "
                    f"Terra's contract names a FAMILY, which does not identify "
                    f"which of them is meant; mechanics will not choose.")
            match = eligible[0]
            if trace is not None:
                trace["tool_detected"] = True
                trace["tool_execution_eligible"] = True
                trace["tool_matched"] = match["tool"]
                trace["tool_matched_source_tf"] = match.get("source_tf")
                trace["tool_rejection_reason"] = None
            return match

        if trace is not None:
            trace["tool_detected"] = False
            trace["tool_execution_eligible"] = False
            trace["tool_rejection_reason"] = "TOOL_NOT_DETECTED"
        raise NoCandidate(
            "tool_not_detected",
            f"TOOL_NOT_DETECTED: {raw!r} — the deterministic toolbox "
            f"detected {[e['tool'] for e in catalog] or 'nothing'} in this "
            f"snapshot. A thesis may not be executed through an expression the "
            f"market never produced.")

    @staticmethod
    def _reference_price(brain_input: dict, direction: str) -> float:
        """The price this candidate is priced from. FRESH, EXECUTABLE, SIDED.

        EXEC-PRICE-FRESHNESS-1 (2026-08-20). This read `market.current_price`,
        which is the newest SETTLED candle close. That number became the
        candidate's `entry_price`, and therefore the origin of every stop
        distance, reward ratio and side-check in this class.

        At 11:02:10 ET it was 29404.25 while the contemporaneous 1m candle ran
        29423.25-29457.25 — a price the market did not trade at any point in
        that minute. Measured against the 29470.25 protected high it produced a
        66.00-point stop and a ceiling veto; the prices actually available
        implied 13.00 to 47.00.

        Ask to buy, bid to sell, and only while the quote is fresh. There is no
        fallback: exposure is never priced from a settled close, because doing
        so is what put a fictional 66-point stop in front of a real trade.
        """
        from broker.topstepx_execution_price import (describe, executable_price,
                                                     refusal)
        market = brain_input.get("market") or {}
        block = market.get("execution_price") or {}
        px = executable_price(block, direction)
        if px is None:
            raise NoCandidate(
                "execution_price_unavailable",
                f"{refusal(block, direction)}: exposure may not be priced from a "
                f"settled candle close ({market.get('settled_price_basis')} "
                f"{market.get('current_price')}). {describe(block)}")
        try:
            px = float(px)
        except (TypeError, ValueError):
            raise NoCandidate("no_reference_price",
                              "executable price is not numeric") from None
        if px <= 0:
            raise NoCandidate("no_reference_price", f"price {px}")
        return px

    def _invalidation(self, parsed: dict, snapshot: dict, brain_input: dict,
                      direction: str, reference_price: float) -> StructuralInvalidation:
        raw = parsed.get("invalidation_level")
        try:
            price = float(raw)
        except (TypeError, ValueError):
            raise NoCandidate("invalidation_missing",
                              "a directional thesis must name a numeric invalidation") from None
        tick = float(getattr(self.contract, "tick_size", 0) or 0)
        if tick > 0 and abs(price / tick - round(price / tick)) > 1e-6:
            raise NoCandidate("invalidation_off_tick", f"{price} is not on the {tick} grid")
        if direction == "bullish" and price >= reference_price:
            raise NoCandidate("invalidation_wrong_side",
                              f"bullish invalidation {price} at/above price {reference_price}")
        if direction == "bearish" and price <= reference_price:
            raise NoCandidate("invalidation_wrong_side",
                              f"bearish invalidation {price} at/below price {reference_price}")

        prot = brain_input.get("protected_swings") or {}
        key = "protected_low" if direction == "bullish" else "protected_high"
        block = prot.get(key) if isinstance(prot.get(key), dict) else {}
        return StructuralInvalidation(
            price=price,
            structure_type=str(parsed.get("narrative_phase") or "thesis_invalidation"),
            structure_identity=f"{key}@{block.get('level', price)}",
            evidence_source=f"luna.invalidation_level+{key}",
            evidence_timestamp=str(brain_input.get("timestamp") or ""))

    def _objective_selected(self, parsed: dict, snapshot: dict,
                            brain_input: dict, direction: str,
                            reference_price: float):
        """The Brain's canonical selection, or None when it did not make one.

        Returning None keeps the legacy prose path available for a Brain that
        has not been given a catalog -- replay of pre-bridge archives must still
        reproduce exactly what happened.
        """
        chosen = parsed.get("objective_id")
        if not chosen:
            return None
        catalog = authorized_objective_catalog(snapshot, brain_input,
                                               reference_price)
        return resolve_objective_by_id(chosen, catalog, direction=direction,
                                       reference_price=reference_price)

    def _objective(self, parsed: dict, snapshot: dict, brain_input: dict,
                   direction: str, reference_price: float,
                   now: datetime) -> LiquidityObjective:
        catalog = enumerate_objectives(snapshot, brain_input)
        if not catalog:
            raise NoCandidate("objective_missing",
                              "the snapshot enumerated no liquidity objectives")
        # CANONICAL SELECTION IS THE PRODUCTION JOIN. Exact identity, no
        # interpretation. Prose resolution survives ONLY for archives written
        # before the catalog was published to the Brain -- gated behind an
        # explicit flag so it can never quietly become the live path again.
        #
        # PROD-20260807 is why: at 09:47:03 the Brain named 29493.25, prose
        # classification reduced that to an objective KIND, side-filtering left
        # exactly one survivor, and the producer bound 29452.50 -- a different
        # level than the Brain chose. It happened to be directionally valid.
        # Accidental correctness is not correctness.
        resolved = self._objective_selected(parsed, snapshot, brain_input,
                                            direction, reference_price)
        if resolved is None:
            if not self.allow_prose_objective_fallback:
                raise NoCandidate(
                    "objective_id_missing",
                    "propose-entry carried no objective_id; the authorized "
                    f"catalog offered {[c.get('objective_id') for c in
                                        authorized_objective_catalog(snapshot, brain_input, reference_price)]}")
            resolved = resolve_objective(parsed.get("active_draw"), catalog,
                                         direction=direction,
                                         reference_price=reference_price)
        trace = getattr(self, "last_decision_trace", None)
        if isinstance(trace, dict):
            trace.update(objective_lookup_found=True,
                         resolved_objective_id=resolved.get("objective_id")
                         or resolved.get("identity"),
                         resolved_objective_type=resolved.get("kind"),
                         resolved_objective_price=resolved.get("price"),
                         objective_side_valid=True, objective_fresh=True,
                         objective_resolution_status="RESOLVED")
        tick = float(getattr(self.contract, "tick_size", 0) or 0)
        if tick > 0 and abs(resolved["price"] / tick - round(resolved["price"] / tick)) > 1e-6:
            raise NoCandidate("objective_off_tick",
                              f"{resolved['price']} is not on the {tick} grid")
        return LiquidityObjective(identity=resolved["identity"], kind=resolved["kind"],
                                  price=resolved["price"], created_at=now, source="luna")

    @staticmethod
    def _objective_evidence(objective: LiquidityObjective, parsed: dict) -> dict:
        return {**objective.evidence(), "objective_type": objective.kind,
                "selected_by": ("brain.objective_id" if parsed.get("objective_id")
                                else "luna.active_draw"),
                "objective_id": parsed.get("objective_id"),
                "luna_draw_text": str(parsed.get("active_draw") or "")[:160],
                "swept": False, "material_delivery_fraction": 0.0,
                "delivery_state": "undelivered_at_creation"}

    @staticmethod
    def _reward_to_risk(entry: float, stop: float, target: float) -> float:
        risk = abs(entry - stop)
        if risk <= 0:
            raise NoCandidate("zero_risk", "invalidation equals the reference price")
        return abs(target - entry) / risk

    def _supersede(self, new: CandidateSnapshot) -> None:
        """One live candidate per lane. The old one is destroyed, never queued."""
        if self.active_candidate is not None:
            self._superseded.append(self.active_candidate.fingerprint())
        self.active_candidate = new

    # ── expiry ────────────────────────────────────────────────────────────────
    def is_expired(self, candidate: CandidateSnapshot, now: datetime = None) -> bool:
        now = now or datetime.now(timezone.utc)
        expires = (candidate.extras or {}).get("candidate_expires_at")
        if not expires:
            return True
        try:
            return now >= datetime.fromisoformat(str(expires))
        except ValueError:
            return True
