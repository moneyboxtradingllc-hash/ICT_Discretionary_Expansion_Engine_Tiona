"""
Toolbox Engine — Phase 1J.
Selects entry tools from existing snapshot evidence.
No execution, no order placement, no indicator recalculation.
"""

import os

from toolbox.tool_library import eligible_tools, preferred_tools, normalize_tool, VALID_TOOLS
from toolbox.tool_readiness import analyze_readiness
from toolbox.price_levels import build_price_level
from toolbox.entry_trigger_prep import build_trigger_prep

_TFS = ["15m", "5m", "3m", "1m"]

_NEUTRAL_TOOL_TOKENS = {"none", "wait", "two_sided_watch", "confirmation_required", ""}


def _brain_preferred_tool(snapshot: dict, pb_dir: str, candidate_tools: list) -> tuple:
    """
    Phase AB-5C — resolve the Brain's recommended_tool_family to a canonical tool
    and validate it is an eligible/ready candidate. Returns (tool|None, note).
    Direction comes from the playbook direction (family tokens are direction-
    agnostic). ECU-gated; never raises.
    """
    if os.getenv("BRAIN_ECU_MODE", "false").lower().strip() != "true":
        return None, None
    bt = snapshot.get("brain_thesis") or {}
    fam = bt.get("tool_family")
    if isinstance(fam, list):
        fam = next((x for x in fam
                    if str(x).lower().strip() not in _NEUTRAL_TOOL_TOKENS), None)
    fam = (str(fam).lower().strip() if fam else "")
    if pb_dir not in ("bullish", "bearish"):
        return None, "non_directional"

    # 1. explicit Brain tool family (preferred when the LLM names a concrete one)
    if fam and fam not in _NEUTRAL_TOOL_TOKENS:
        cand = fam if fam in VALID_TOOLS else f"{pb_dir}_{fam}"
        if cand not in VALID_TOOLS:
            cand = normalize_tool(cand) or normalize_tool(fam)
        if cand and cand in candidate_tools:
            return cand, "ai_brain_selected"
        return None, f"brain_tool_{fam}_not_eligible_or_ready"

    # 2. Brain emitted no concrete tool → derive from the Brain-chosen playbook's
    #    canonical preferred tool (a deterministic consequence of the Brain's
    #    playbook+direction). Still Brain-owned (not mechanical score-ranking).
    pb = (snapshot.get("playbook", {}) or {}).get("selected_playbook")
    for t in preferred_tools(pb, pb_dir):
        if t in candidate_tools:
            return t, "ai_brain_playbook_derived"
    return None, "no_brain_tool_family"

_NO_TOOLBOX = {
    "preferred_tool":                  None,
    "toolbox_status":                  "no_tool",
    "tool_confidence":                 0,
    "near_tie_tools":                  [],
    "tool_candidates":                 [],
    "warnings":                        [],
    "best_available_raw_status":       "no_tool",
    "best_available_effective_status": "no_tool",
}

# Rank: lower number = better status
_RAW_RANK = {"actionable": 0, "ready": 1, "forming": 2, "no_tool": 3}
_EFF_RANK = {"actionable": 0, "ready": 1, "forming": 2, "blocked_by_risk": 3, "no_tool": 4}


# ── Direction / family helpers ────────────────────────────────────────────────

def _tool_direction(tool: str) -> str:
    if tool.startswith("bullish_"): return "bullish"
    if tool.startswith("bearish_"): return "bearish"
    return "neutral"


def _family(tool: str) -> str:
    for p in ("bullish_", "bearish_"):
        if tool.startswith(p):
            return tool[len(p):]
    return tool


# ── Shared context score (0–20) ───────────────────────────────────────────────

def _context_score(snapshot: dict) -> int:
    struct = snapshot.get("structure", {})
    exp    = snapshot.get("expansion",  {})
    vol    = snapshot.get("volatility", {})
    mem    = snapshot.get("memory",     {})
    pts    = 0

    align = struct.get("alignment", "neutral")
    pts += {"full": 8, "strong": 6, "partial": 3}.get(align, 0)

    if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
           for tf in _TFS):
        pts += 5

    if vol.get("15m", {}).get("state") not in ("toxic", "explosive"):
        pts += 4

    g = (mem.get("global") or {}) if mem and mem.get("available") else {}
    if g.get("confidence_trend") == "rising":
        pts += 3

    return min(20, pts)


# ── Family evidence scorers (0–80) ────────────────────────────────────────────

# ── ANCHOR-LOCAL FAMILY EVIDENCE (Phase 1E, 2026-08-12) ──────────────────────
#: A tool's PHYSICAL EXISTENCE is a local fact. Its CONTEXT may be global. The
#: previous scorers blurred the two: every family evidence test was
#: `any(... for tf in _TFS)`, so a 1m-anchored bearish IFVG collected points from
#: a 5m sweep it had nothing to do with, and two oppositely-anchored tools came
#: back with the same number from the same shared evidence.
#:
#: A fact may INFLUENCE another fact without IMPERSONATING it. So the score is
#: split and both halves are reported:
#:
#:   local_evidence  — only the anchor timeframe's own liquidity/structure facts
#:   global_context  — market-wide terms (alignment, expansion, volatility,
#:                     PO3, memory), explicitly labelled as context
#:
#: Weights are carried over from the original scorers unchanged. Nothing here is
#: retuned; the terms are only attributed to the right owner.

def _tf_block(snap: dict, block: str, tf: str) -> dict:
    return (snap.get(block, {}).get(tf) or {})


def _local_ifvg(snap: dict, tf: str) -> int:
    liq = _tf_block(snap, "liquidity", tf)
    pts = 20
    if liq.get("sweep_detected"):   pts += 20
    if liq.get("reclaim_detected"): pts += 15
    return pts


def _local_breaker(snap: dict, tf: str) -> int:
    liq, st = _tf_block(snap, "liquidity", tf), _tf_block(snap, "structure", tf)
    pts = 20
    if liq.get("failed_breakout"):  pts += 20
    if liq.get("sweep_detected"):   pts += 15
    if liq.get("reclaim_detected"): pts += 10
    if st.get("mss"):               pts += 10
    if st.get("bos"):               pts += 5
    return pts


def _local_rejection_block(snap: dict, tf: str) -> int:
    liq = _tf_block(snap, "liquidity", tf)
    pts = 20
    if liq.get("sweep_detected"):   pts += 20
    if liq.get("reclaim_detected"): pts += 15
    return pts


def _local_ote_after_reclaim(snap: dict, tf: str) -> int:
    liq = _tf_block(snap, "liquidity", tf)
    pts = 20
    if liq.get("sweep_detected"):   pts += 20
    if liq.get("reclaim_detected"): pts += 15
    return pts


def _local_order_block(snap: dict, tf: str) -> int:
    st = _tf_block(snap, "structure", tf)
    pts = 20
    if st.get("bos"): pts += 15
    if st.get("mss"): pts += 10
    return pts


def _local_ote_retracement(snap: dict, tf: str) -> int:
    st = _tf_block(snap, "structure", tf)
    pts = 20
    if st.get("bos"): pts += 10
    if st.get("mss"): pts += 10
    return pts


def _local_range_break_retest(snap: dict, tf: str) -> int:
    st = _tf_block(snap, "structure", tf)
    pts = 20
    if st.get("bos"): pts += 15
    if st.get("mss"): pts += 5
    return pts


def _local_opening_order_block(snap: dict, tf: str) -> int:
    if snap.get("session") != "ny_open":
        return 0
    st = _tf_block(snap, "structure", tf)
    pts = 25                                    # session gate
    if st.get("bos"): pts += 10
    if st.get("mss"): pts += 7
    return pts


def _local_fvg(snap: dict, tf: str) -> int:
    """STEP 4B.12 §6 UNIT 6 (F-7) — the ORIGINAL FVG scoring terms, restored.

    Not invented here. These are `_score_fvg` from the initial commit
    (4139c77), the same three terms `_readiness_fvg` still narrates to Terra:
    displacement on 15m/5m, expansion state on 15m/5m, and a bonus when no
    sweep has disturbed the clean-continuation context.

    THESE TERMS ARE MARKET CONTEXT, NOT PROPERTIES OF ONE GAP, and they are
    deliberately left that way -- Unit 6 does not rewrite scoring doctrine. Two
    occurrences on the same timeframe therefore score the same, which is honest:
    what distinguishes them is identity, geometry and lifecycle, not this score.
    A tie is NEVER a licence to collapse them into one instance.
    """
    exp = snap.get("expansion", {})
    liq = snap.get("liquidity", {})
    pts = 20
    if any(exp.get(t, {}).get("displacement_detected") for t in ("15m", "5m")):
        pts += 25
    if any(exp.get(t, {}).get("state") in ("early_expansion", "healthy_expansion")
           for t in ("15m", "5m")):
        pts += 15
    if not any(liq.get(t, {}).get("sweep_detected") for t in _TFS):
        pts += 5
    return pts


_LOCAL_SCORERS = {
    "fvg":                 _local_fvg,
    "ifvg":                _local_ifvg,
    "breaker":             _local_breaker,
    "rejection_block":     _local_rejection_block,
    "ote_after_reclaim":   _local_ote_after_reclaim,
    "order_block":         _local_order_block,
    "ote_retracement":     _local_ote_retracement,
    "range_break_retest":  _local_range_break_retest,
    "opening_order_block": _local_opening_order_block,
    # fvg / opening_fvg / mss_retest are direction-blind and never scored.
}


def _family_context_score(family: str, snap: dict) -> int:
    """Market-wide terms carried over verbatim from the original scorers.

    These are genuinely not properties of the anchor bar -- higher-timeframe
    alignment, PO3 phase, expansion regime, volatility. They may inform many
    tools at once. What they may NOT do is stand in for the local evidence that
    made a specific tool exist.
    """
    exp = snap.get("expansion", {})
    po3 = snap.get("po3", {})
    struct = snap.get("structure", {})
    vol = snap.get("volatility", {})
    pts = 0

    if family in ("ifvg", "ote_after_reclaim"):
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["3m", "1m"]):
            pts += 10
    if family == "ifvg":
        if any(po3.get(tf, {}).get("phase") in ("manipulation", "transition")
               for tf in ["3m", "1m"]):
            pts += 5
        if po3.get("alignment") == "full_distribution_alignment":
            pts -= 10
    if family == "ote_after_reclaim":
        if struct.get("alignment") in ("neutral", "partial"):
            pts += 5
    if family == "rejection_block":
        for tf in ["15m", "5m"]:
            ex = exp.get(tf, {})
            if ex.get("exhaustion_risk") == "high":
                pts += 10
                break
            if ex.get("exhaustion_risk") == "medium" and \
                    ex.get("state") in ("mature_expansion", "exhaustion_risk"):
                pts += 5
                break
    if family in ("order_block", "ote_retracement"):
        align = struct.get("alignment", "neutral")
        table = ({"full": 20, "strong": 15, "partial": 8} if family == "order_block"
                 else {"full": 15, "strong": 10, "partial": 5})
        pts += table.get(align, 0)
        if any(exp.get(tf, {}).get("state") in ("healthy_expansion", "mature_expansion")
               for tf in ["15m", "5m"]):
            pts += 10 if family == "order_block" else 15
        if any(po3.get(tf, {}).get("phase") == "distribution" for tf in ["15m", "5m"]):
            pts += 5 if family == "order_block" else 10
        if family == "order_block" and any(
                exp.get(tf, {}).get("exhaustion_risk") == "high" for tf in ["15m", "5m"]):
            pts -= 10
    if family == "range_break_retest":
        if struct.get("15m", {}).get("state") in ("range_bound", "neutral"):
            pts += 20
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["1m", "3m", "5m"]):
            pts += 10
    if family == "opening_order_block":
        pts += {"full": 15, "strong": 12, "partial": 7}.get(
            struct.get("alignment", "neutral"), 0)
        vs = vol.get("15m", {}).get("state", "")
        if vs in ("expanding", "stable"):   pts += 10
        if vs in ("toxic", "explosive"):    pts -= 20
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["1m", "3m", "5m"]):
            pts += 10
    return pts


# ── Status resolution ─────────────────────────────────────────────────────────

def _raw_status(score: int) -> str:
    """Score-only verdict. Risk Governor has no input here."""
    if score < 40:  return "no_tool"
    if score >= 75: return "actionable"
    if score >= 60: return "ready"
    return "forming"


def _effective_status(raw: str, risk_blocked: bool) -> str:
    """Apply Risk Governor override on top of the raw score verdict."""
    if raw == "no_tool":
        return "no_tool"
    return "blocked_by_risk" if risk_blocked else raw


# ── Score a single tool ───────────────────────────────────────────────────────

# ── DIRECTIONAL TRUTH (2026-08-12) ───────────────────────────────────────────
#: Every family scorer takes `direction` and NOT ONE OF THEM READS IT. They score
#: undirected booleans -- sweep_detected, mss, bos, displacement_detected -- so
#: `bullish_ifvg` and `bearish_ifvg` returned IDENTICAL scores on the same
#: snapshot (72/72, 77/77 measured on PROD-20260812-PM). That was survivable only
#: because `run_toolbox` scored a single mechanically preselected side: the label
#: was true by assumption, never by evidence.
#:
#: The moment Terra owns direction, that assumption is gone and the label has to
#: be EARNED. A scorer that cannot prove its side does not get to claim one.
#:
#: The gate lives here rather than inside each scorer because `_score_tool` adds
#: `_context_score` to whatever the family returns -- a scorer returning 0 could
#: still clear the 40-point `no_tool` threshold on context alone and emit a
#: phantom tool.
_REVERSAL_FAMILIES = ("ifvg", "breaker", "rejection_block", "ote_after_reclaim")
_CONTINUATION_FAMILIES = ("order_block", "ote_retracement", "range_break_retest",
                          "opening_order_block")
#: FAIL CLOSED. These have no directional evidence in the snapshot at all:
#: `mss` is a bare boolean with no `mss_direction`, and displacement records
#: `directional_efficiency` (a magnitude) but no side. Deriving their direction
#: from `bos_direction` would rebuild the exact authority inversion one layer
#: down -- "mechanics said bearish, therefore this FVG is bearish". Until their
#: own detectors witness a side, they are not offerable in either direction.
#:
#: STEP 4B.12 §6 UNIT 6 (F-7) — `fvg` REMOVED, because its premise was never
#: true of the object.
#:
#: The LAW above is untouched and still governs `opening_fvg` and `mss_retest`:
#: no family may borrow a side from BOS, bias, liquidity or a caller's request.
#: What was wrong was the classification. A plain FVG proves its own side from
#: the exact source triple -- `c1.high < c3.low` is bullish, `c1.low > c3.high`
#: is bearish, and the two are mutually exclusive on one triple -- and
#: `find_fvgs` has enforced exactly that since the initial commit (4139c77),
#: over two months BEFORE this guard was written on 2026-08-14. The same commit
#: that declared FVG direction-blind also wrote, in `market_events`, "an FVG
#: proves its own side or it is not an FVG". Both shipped together.
#:
#: The consequence was total: `_anchor_tfs` returned [] for every scan, so a
#: canonical tool family produced zero instances, zero candidates and zero
#: catalog entries. Measured on the venue tape, the producer knew a lawful
#: bullish occurrence on 250/250 scans and a bearish one on 206/250 -- 92 unique
#: lawful occurrence identities -- and Terra was told none of them existed.
#:
#: `fvg` is removed here ONLY because the occurrence-owned witness below now
#: supplies its side from the gap itself. The guard is not weakened; the family
#: simply stopped belonging in it.
_DIRECTION_BLIND_FAMILIES = ("opening_fvg", "mss_retest")


#: PROVENANCE COUPLING. A first attempt gated on "does this direction exist
#: ANYWHERE in the snapshot", which is a different claim from "this tool is
#: directionally proven". Measured on PROD-20260812-PM: on 7 of 81 scans two
#: timeframes swept opposite ways (1m above_high, 5m below_low), both directions
#: were admitted globally, and the 72/72 mirror returned intact. The trigger and
#: the direction were coming from different events.
#:
#: A tool is therefore anchored to the SPECIFIC timeframe whose own evidence
#: witnesses it: the sweep that makes a reversal detectable is the same sweep
#: that gives it its side, and the break that makes a continuation detectable is
#: the same break that gives it its side. No anchor, no tool.
_SWEEP_SIDE = {"above_high": "bearish", "below_low": "bullish"}


def _anchor_tfs(family: str, direction: str, snap: dict) -> list:
    """Timeframes whose OWN evidence witnesses this family in this direction.

    Returned in `_TFS` order so the anchor is deterministic. An empty list means
    the tool is not physically detectable on that side, whatever else the
    snapshot happens to contain elsewhere.
    """
    if direction not in ("bullish", "bearish") or family in _DIRECTION_BLIND_FAMILIES:
        return []
    out = []
    for tf in _TFS:
        if family in _REVERSAL_FAMILIES:
            d = (snap.get("liquidity", {}).get(tf) or {}).get("sweep_direction")
            if _SWEEP_SIDE.get(d) == direction:
                out.append(tf)
        elif family in _CONTINUATION_FAMILIES:
            st = snap.get("structure", {}).get(tf) or {}
            if st.get("bos_direction") == direction or \
                    str(st.get("state") or "").startswith(direction):
                out.append(tf)
    return out


def _direction_supported(family: str, direction: str, snap: dict) -> bool:
    """Is THIS tool, on THIS side, anchored to evidence that actually witnessed it?"""
    return bool(_anchor_tfs(family, direction, snap))


def tool_provenance(tool: str, snap: dict) -> dict:
    """The witness a directional tool carries: which timeframe proves its side.

    Public because a tool Terra can choose must be a tool she can be REFUSED for
    choosing: Step 7 has to be able to check the same anchor that authorised it.
    """
    fam, direction = _family(tool), _tool_direction(tool)
    tfs = _anchor_tfs(fam, direction, snap)
    witness = None
    if tfs and fam in _REVERSAL_FAMILIES:
        witness = (snap.get("liquidity", {}).get(tfs[0]) or {}).get("sweep_direction")
    elif tfs and fam in _CONTINUATION_FAMILIES:
        st = snap.get("structure", {}).get(tfs[0]) or {}
        witness = st.get("bos_direction") or st.get("state")
    return {"tool": tool, "family": fam, "direction": direction,
            "source_tf": tfs[0] if tfs else None, "anchor_tfs": tfs,
            "directional_witness": witness, "directionally_proven": bool(tfs)}


def score_instance(tool: str, snapshot: dict, tf: str) -> "dict | None":
    """One anchored tool INSTANCE, with its score attributed to its two owners.

    `None` when this tool is not physically witnessed on this timeframe in this
    direction -- absence is reported as absence, never as a weak score.
    """
    fam, direction = _family(tool), _tool_direction(tool)
    if tf not in _anchor_tfs(fam, direction, snapshot):
        return None
    local = _LOCAL_SCORERS.get(fam)
    if local is None:
        return None
    local_score = local(snapshot, tf)
    context = _family_context_score(fam, snapshot) + _context_score(snapshot)
    prov = tool_provenance(tool, snapshot)
    return {"tool_id": f"{tool}@{tf}", "tool": tool, "family": fam,
            "direction": direction, "source_tf": tf,
            "directional_witness": prov["directional_witness"],
            "local_evidence_score": local_score,
            "global_context_score": context,
            "score": max(0, min(100, local_score + context))}


#: Cadence for the plain-FVG occupancy path, keyed the way `price_levels` keys.
_TF_MINUTES_FOR_FVG = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}


def fvg_occurrence_instances(tool: str, snapshot: dict) -> list:
    """One addressable instance per exact plain-FVG OCCURRENCE.

    STEP 4B.12 §6 UNIT 6 (F-7) — OCCURRENCE-OWNED, NOT TIMEFRAME-OWNED.

    `_anchor_tfs` answers "which timeframe", which is the right question for a
    family whose side comes from a sweep or a break. It is the WRONG question
    here: reducing several exact gaps to `["5m", "15m"]` before instance
    creation would destroy the occurrence identity Unit 6 exists to preserve,
    and two lawful gaps on one timeframe would silently become one tool.

    So plain FVG builds its instances from the occurrences themselves. The
    directional witness is the gap's own geometry, supplied by `find_fvgs` --
    NOT by BOS, bias, liquidity, or the fact that the caller asked for a
    bullish tool. `direction` FILTERS which predicate is tested; an occurrence
    that fails it is simply not returned, so a bearish triple can never arrive
    under a bullish request.

    FOUR SEPARATE PROPOSITIONS travel with each instance and are never
    collapsed into one another:

        occurrence exists / has identity     (contract + tf + completion slot)
        intrinsic direction                  (the gap's own geometry)
        lifecycle authority                  (evaluable, and not retired)
        temporal execution authority         (CONTINUITY-2F, decided later by
                                              `build_price_level`'s dual-arm
                                              comparison -- NOT asserted here)

    A forming or retired occurrence stays OBSERVABLE and is published carrying
    its reason. Observable is not lawful, and lawful lifecycle is not temporal
    execution authority.
    """
    from toolbox.price_levels import fvg_execution_instances

    fam, direction = _family(tool), _tool_direction(tool)
    if fam != "fvg" or direction not in ("bullish", "bearish"):
        return []
    local = _LOCAL_SCORERS.get(fam)
    if local is None:
        return []
    tfs = snapshot.get("timeframes", {}) or {}
    out = []
    for tf in _TFS:
        mins = _TF_MINUTES_FOR_FVG.get(tf)
        if mins is None:
            continue
        candles = (tfs.get(tf, {}) or {}).get("recent_candles") or []
        if not candles:
            continue
        # PLAIN-FVG-EXECUTABLE-REPRESENTATION-1. The snapshot carries the exact
        # contract so identity can be minted; absent it, occurrences stay
        # anonymous and are dropped below, exactly as before this unit.
        for occ in fvg_execution_instances(candles, direction, mins,
                                           contract=snapshot.get("contract_id")):
            if not occ.get("occurrence_id"):
                continue          # no provable identity is not a tool
            local_score = local(snapshot, tf)
            context = _family_context_score(fam, snapshot) + _context_score(snapshot)
            out.append({
                # `tool_id` stays "<tool>@<tf>" shaped and gains the completion
                # slot, so several occurrences on one timeframe remain distinct
                # and deterministically ordered.
                "tool_id": f"{tool}@{tf}#{occ['c3_time']}",
                "tool": tool, "family": fam, "direction": direction,
                "source_tf": tf,
                # THE WITNESS, NAMED. Not a sweep, not a break -- the gap.
                "directional_witness": "fvg_occurrence_geometry",
                "occurrence_id": occ["occurrence_id"],
                "identity_evaluable": bool(occ.get("identity_evaluable")),
                "formation_c1_time": occ.get("c1_time"),
                "formation_c2_time": occ.get("c2_time"),
                "formation_c3_time": occ.get("c3_time"),
                "zone_low": occ.get("low"), "zone_high": occ.get("high"),
                "occurrence_lifecycle": {
                    k: occ.get(k) for k in
                    ("entered", "fully_traversed", "close_through_far_boundary",
                     "retired", "retirement_reason", "retirement_bar",
                     "bars_since_formation", "lifecycle_evaluable",
                     "lifecycle_reason")},
                # PER-OCCURRENCE authority, every witness preserved.
                "occurrence_execution_eligible": bool(occ.get("execution_eligible")),
                "occurrence_ineligible_reason": occ.get("execution_ineligible_reason"),
                "temporal_class": occ.get("temporal_class"),
                "temporal_execution_eligible": bool(occ.get("temporal_execution_eligible")),
                "execution_eligible": bool(occ.get("execution_eligible")),
                "execution_ineligible_reason": occ.get("execution_ineligible_reason"),
                "local_evidence_score": local_score,
                "global_context_score": context,
                "score": max(0, min(100, local_score + context)),
            })
    return out


def tool_instances(snapshot: dict) -> list:
    """Every physically witnessed, directionally proven tool instance.

    A family witnessed on two timeframes yields TWO instances, not one object
    with a list of anchors: a 1m bearish IFVG and a 5m bearish IFVG are
    different market objects, and a discretionary selector has to be able to
    pick the one it actually means.

    UNIT 6 (F-7): plain FVG extends that same principle one level further --
    two gaps on ONE timeframe are also different market objects, so it produces
    one instance per exact occurrence. Every other family is untouched.
    """
    out = []
    for tool in VALID_TOOLS:
        fam, direction = _family(tool), _tool_direction(tool)
        if fam == "fvg":
            out.extend(i for i in fvg_occurrence_instances(tool, snapshot)
                       if _raw_status(i["score"]) != "no_tool")
            continue
        for tf in _anchor_tfs(fam, direction, snapshot):
            inst = score_instance(tool, snapshot, tf)
            if inst and _raw_status(inst["score"]) != "no_tool":
                out.append(inst)
    return sorted(out, key=lambda e: (-e["score"], e["tool_id"]))


def _score_tool(tool: str, snapshot: dict) -> int:
    """Best instance score for a tool, or 0 when no instance is witnessed.

    Kept for the existing single-score callers; `tool_instances` is the truthful
    shape and the one a selector should be given.
    """
    fam, direction = _family(tool), _tool_direction(tool)
    best = 0
    for tf in _anchor_tfs(fam, direction, snapshot):
        inst = score_instance(tool, snapshot, tf)
        if inst:
            best = max(best, inst["score"])
    return best


# ── Reasons ───────────────────────────────────────────────────────────────────

def _tool_reasons(tool: str, snapshot: dict) -> list:
    fam    = _family(tool)
    liq    = snapshot.get("liquidity",  {})
    struct = snapshot.get("structure",  {})
    exp    = snapshot.get("expansion",  {})
    po3    = snapshot.get("po3",        {})
    pb     = snapshot.get("playbook",   {})

    pb_name = pb.get("selected_playbook", "unknown")
    r = [f"Tool eligible for {pb_name}"]

    sweep   = any(liq.get(tf, {}).get("sweep_detected")   for tf in _TFS)
    reclaim = any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS)
    failed  = any(liq.get(tf, {}).get("failed_breakout")  for tf in _TFS)
    mss     = any(struct.get(tf, {}).get("mss")           for tf in _TFS)
    bos     = any(struct.get(tf, {}).get("bos")           for tf in _TFS)
    disp    = any(exp.get(tf, {}).get("displacement_detected") for tf in ["15m", "5m"])
    align   = struct.get("alignment", "neutral")

    if fam in ("ifvg", "breaker", "rejection_block", "ote_after_reclaim"):
        if sweep and reclaim: r.append("Sweep and reclaim confirmed")
        elif sweep:           r.append("Sweep detected — reclaim pending")

    if fam == "ifvg":
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["3m", "1m"]):
            r.append("Expansion beginning after reclaim")
        if any(po3.get(tf, {}).get("phase") in ("manipulation", "transition")
               for tf in ["3m", "1m"]):
            r.append("Lower timeframe PO3 in manipulation/transition phase")

    if fam == "breaker":
        if failed: r.append("Failed breakout creates breaker context")
        if mss:    r.append("Market structure shift present")
        if bos:    r.append("Break of structure confirmed")

    if fam == "rejection_block":
        for tf in ["15m", "5m"]:
            if exp.get(tf, {}).get("exhaustion_risk") in ("high", "medium"):
                r.append(f"{tf} expansion exhaustion supports wick rejection zone")
                break

    if fam in ("fvg", "order_block"):
        if disp: r.append("Displacement candle confirmed")
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["15m", "5m"]):
            r.append("Expansion in progress")

    if fam == "fvg" and not sweep:
        r.append("Clean directional move — no sweep interference")

    if fam == "order_block":
        if any(po3.get(tf, {}).get("phase") == "distribution" for tf in ["15m", "5m"]):
            r.append("PO3 distribution phase active on higher timeframe")

    if fam == "ote_retracement":
        if any(exp.get(tf, {}).get("state") in ("mature_expansion", "healthy_expansion")
               for tf in ["15m", "5m"]):
            r.append("Mature expansion suggests pullback into OTE zone")
        if any(po3.get(tf, {}).get("phase") == "distribution" for tf in ["15m", "5m"]):
            r.append("PO3 distribution supports continuation after pullback")

    if fam == "mss_retest":
        if mss:    r.append("MSS confirmed — retest opportunity forming")
        if bos:    r.append("BOS present — structural momentum")
        if reclaim: r.append("Reclaim adds structural confluence")

    if fam == "ote_after_reclaim":
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["3m", "1m"]):
            r.append("Lower timeframe expansion beginning — OTE zone active")
        if align in ("neutral", "partial"):
            r.append("Neutral/partial alignment — pullback completing")

    if fam in ("opening_fvg", "opening_order_block"):
        r.append("NY Open session — early window active")
        if disp: r.append("Displacement at open confirmed")

    if fam == "range_break_retest":
        if struct.get("15m", {}).get("state") in ("range_bound", "neutral"):
            r.append("15m was range-bound — breakout in progress")
        if bos: r.append("Break of structure confirms range exit")
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["1m", "3m", "5m"]):
            r.append("Expansion beginning after range break")

    if align in ("full", "strong"):
        r.append(f"MTF structure alignment: {align}")

    return r


# ── Warnings ──────────────────────────────────────────────────────────────────

def _tool_warnings(tool: str, snapshot: dict, risk_blocked: bool) -> list:
    w   = []
    vol = snapshot.get("volatility", {})
    exp = snapshot.get("expansion",  {})
    pb  = snapshot.get("playbook",   {})

    if risk_blocked:
        w.append("Risk Governor blocked — analysis only, no execution")

    if vol.get("15m", {}).get("state") in ("toxic", "explosive"):
        w.append("15m volatility elevated — entry timing critical")

    for tf in ["15m", "5m"]:
        if exp.get(tf, {}).get("exhaustion_risk") == "high":
            w.append(f"{tf} expansion exhaustion risk high — late entry risk")
            break

    if pb.get("direction") in ("neutral", "conflicted"):
        w.append("Playbook direction unconfirmed — tool directional bias not validated")

    return w


# ── Public entry point ────────────────────────────────────────────────────────

def run_toolbox(snapshot: dict) -> dict:
    """
    Phase 1J — Toolbox Engine.
    Reads the fully assembled snapshot (including playbook + risk) and returns
    tool selection results.  Only canonical tools are scored.
    """
    pb   = snapshot.get("playbook", {})
    risk = snapshot.get("risk",     {})

    pb_name      = pb.get("selected_playbook", "no_playbook")
    pb_dir       = pb.get("direction", "neutral")
    risk_blocked = not risk.get("trade_allowed", True)

    # ── PHASE 2 (2026-08-12) — THE CAGE IS GONE ──────────────────────────────
    # Two early returns used to live here:
    #
    #     if pb_name == "no_playbook":            return _NO_TOOLBOX
    #     if pb_dir not in ("bullish","bearish"): return _NO_TOOLBOX
    #
    # They meant tool DETECTION never ran unless a mechanical selector had
    # already chosen a playbook and a side. Measured on PROD-20260812-PM: 58 of
    # 81 scans returned `tool_candidates: []` — and re-scoring those same
    # snapshots showed 52 of them held truthful directional inventory the whole
    # time. Nobody had looked.
    #
    # A physical IFVG does not stop existing because the deterministic selector
    # preferred another playbook. Physical existence is generated FIRST, for
    # BOTH directions, every scan. Playbook compatibility is a ranking question
    # and belongs downstream, not a permission to exist.
    #
    # `pb_name` / `pb_dir` are still read below as CONTEXT for ranking and are
    # reported as such. They no longer decide whether a side is evaluated.
    instances = tool_instances(snapshot)

    # Compatibility: `tool_candidates` is consumed in a dozen places, one of
    # which keys a dict by `tool`, so it stays one entry per tool name -- the
    # best-scoring instance, carrying its own anchor. The full instance list is
    # published alongside it and is the truthful shape for a selector.
    best_by_tool = {}
    for inst in instances:                       # already sorted best-first
        best_by_tool.setdefault(inst["tool"], inst)

    candidates = []
    for tool, inst in best_by_tool.items():
        score = inst["score"]
        raw   = _raw_status(score)
        if raw == "no_tool":
            continue
        eff      = _effective_status(raw, risk_blocked)
        readiness = analyze_readiness(tool, snapshot, score, raw)
        pl        = build_price_level(tool, snapshot)
        tp        = build_trigger_prep(tool, snapshot, pl, readiness, raw, eff)
        candidates.append({
            "tool":             tool,
            "tool_id":          inst["tool_id"],
            "direction":        inst["direction"],
            "source_tf":        inst["source_tf"],
            "directional_witness":  inst["directional_witness"],
            "local_evidence_score": inst["local_evidence_score"],
            "global_context_score": inst["global_context_score"],
            "score":            score,
            "raw_status":       raw,
            "effective_status": eff,
            "reasons":          _tool_reasons(tool, snapshot),
            "warnings":         _tool_warnings(tool, snapshot, risk_blocked),
            "readiness":        readiness,
            "price_level":      pl,
            "trigger_prep":     tp,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    if not candidates:
        # Factual absence: both sides WERE evaluated and nothing was witnessed.
        # Distinct from the old "toolbox cannot activate", which meant nobody looked.
        result = _NO_TOOLBOX.copy()
        result["warnings"] = ["both directions evaluated; no tool instance was "
                              "physically witnessed above threshold (score < 40)"]
        result["tool_instances"] = []
        result["bullish_instances"] = []
        result["bearish_instances"] = []
        result["mechanical_playbook_context"] = pb_name
        result["mechanical_direction_context"] = pb_dir
        return result

    # ── Phase AB-5C — ECU: the Brain SELECTS the tool ────────────────────────
    # Under BRAIN_ECU_MODE the Brain's recommended_tool_family designates the
    # preferred tool; the toolbox is the validator (it scored readiness above and
    # rejects the Brain's choice if it is not eligible/ready). Mechanical ranking
    # (candidates[0]) is only the fallback when the Brain names no eligible tool.
    preferred = candidates[0]
    preferred_source = "mechanical"
    brain_pick, brain_note = _brain_preferred_tool(snapshot, pb_dir,
                                                   [c["tool"] for c in candidates])
    if brain_pick:
        preferred = next(c for c in candidates if c["tool"] == brain_pick)
        preferred_source = brain_note   # ai_brain_selected | ai_brain_playbook_derived

    near_tie = [
        c["tool"] for c in candidates[1:]
        if preferred["score"] - c["score"] <= 5
    ]

    global_warnings = []
    if risk_blocked:
        global_warnings.append("Toolbox found valid tools but Risk Governor is blocked")
    if near_tie:
        global_warnings.append("multiple tools competing — market context may be ambiguous")

    best_raw = min(candidates, key=lambda c: _RAW_RANK.get(c["raw_status"], 99))["raw_status"]
    best_eff = min(candidates, key=lambda c: _EFF_RANK.get(c["effective_status"], 99))["effective_status"]

    if brain_note and not brain_pick:
        global_warnings.append(f"ECU: {brain_note} — validator fallback to mechanical rank")

    return {
        "preferred_tool":                  preferred["tool"],
        "preferred_tool_source":           preferred_source,   # AB-5C: ai_brain | mechanical
        "toolbox_status":                  preferred["effective_status"],
        "tool_confidence":                 preferred["score"],
        "near_tie_tools":                  near_tie,
        "tool_candidates":                 candidates,
        # PHASE 2: the truthful shape. One entry per PHYSICALLY WITNESSED
        # instance, so `bearish_ifvg@1m` and `bearish_ifvg@5m` stay two objects.
        # `tool_candidates` above collapses to one entry per tool name only
        # because a dozen existing consumers key on it.
        "tool_instances":                  instances,
        "bullish_instances":               [i for i in instances
                                            if i["direction"] == "bullish"],
        "bearish_instances":               [i for i in instances
                                            if i["direction"] == "bearish"],
        # Recorded as CONTEXT. Phase 2 proves these can no longer decide whether
        # a side was generated; Phase 3 renames them to say so.
        "mechanical_playbook_context":     pb_name,
        "mechanical_direction_context":    pb_dir,
        "warnings":                        global_warnings,
        "best_available_raw_status":       best_raw,
        "best_available_effective_status": best_eff,
    }
