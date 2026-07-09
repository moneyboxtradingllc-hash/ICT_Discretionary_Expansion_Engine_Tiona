"""
Trade Qualification Engine — final decision layer.
Reads all existing snapshot intelligence and answers:
  Is there an opportunity? How good? Worth attention? Stand down?

Does NOT execute trades, size positions, or place orders.
All inputs are pre-computed snapshot dicts — no recalculation here.
"""
import os

TIMEFRAMES = ["15m", "5m", "3m", "1m"]

# ── Scoring tables ────────────────────────────────────────────────────────────

NARRATIVE_QUALITY = {
    "bullish_continuation_after_manipulation": 25,
    "bearish_continuation_after_manipulation": 25,
    "distribution_in_progress":                22,
    "liquidity_sweep_reversal":                20,
    "bullish_continuation":                    18,
    "bearish_continuation":                    18,
    "accumulation_before_expansion":           12,
    "manipulation_without_distribution":        8,
    "range_expansion":                          8,
    "neutral":                                  3,
    "exhaustion_risk":                          0,
    "conflicted":                               0,
    "compression":                              0,
}

PO3_ALIGNMENT_QUALITY = {
    "full_distribution_alignment":  20,
    "manipulation_to_distribution": 17,
    "accumulation_building":         9,
    "mixed":                         4,
    "no_clear_alignment":            1,
}

STRUCTURE_ALIGNMENT_QUALITY = {
    "full":    15,
    "strong":  11,
    "partial":  6,
    "mixed":    2,
    "neutral":  0,
}

STATUS_TIERS = [
    (85, "elite"),
    (70, "qualified"),
    (55, "candidate"),
    (40, "watchlist"),
    (0,  "no_trade"),
]

GRADE_MAP = [
    (95, "A+"),
    (85, "A"),
    (70, "B"),
    (55, "C"),
    (40, "D"),
    (0,  "F"),
]

_NO_TRADE_NARRATIVES = {"conflicted", "exhaustion_risk", "compression"}

# ── Phase AB-7.3c — qualification stability floor ─────────────────────────────
# Status tiers from weakest to strongest. A mature persistent thesis prevents a
# single-scan mechanical dip from collapsing qualified->no_trade. The floor only
# RAISES the status tier; it never fabricates the opportunity score and never
# overrides a hard disqualification (true danger still forces no_trade).
_STATUS_ORDER = ["no_trade", "watchlist", "candidate", "qualified", "elite"]
_THESIS_STATUS_FLOOR = {"EXECUTABLE": "qualified", "ACTIVE": "candidate"}


def _thesis_floor_enabled() -> bool:
    """Default false: legacy behavior, qualification bit-for-bit unchanged."""
    return os.getenv("QUALIFICATION_THESIS_FLOOR", "false").lower().strip() == "true"


def _apply_thesis_floor(status: str, direction: str, disqualified: bool,
                        thesis_state: dict) -> tuple:
    """Return (status, floor_applied). Raises status to the thesis-implied floor
    when a mature trade thesis is held and the mechanical status sits below it."""
    if disqualified or not _thesis_floor_enabled():
        return status, False
    ts = thesis_state or {}
    if not (ts.get("present") and ts.get("is_trade_thesis")):
        return status, False
    floor = _THESIS_STATUS_FLOOR.get(ts.get("thesis_status"))
    if not floor:
        return status, False   # THREATENED / WEAKENING / INVALIDATED → no floor
    # Never floor against a hard directional contradiction with the thesis.
    tdir = ts.get("direction")
    if (direction in ("bullish", "bearish") and tdir in ("bullish", "bearish")
            and direction != tdir):
        return status, False
    if _STATUS_ORDER.index(status) < _STATUS_ORDER.index(floor):
        return floor, True
    return status, False


# ── AI-AUTH-2 — Brain conversion floor ───────────────────────────────────────
# When the HEALTHY LLM Brain authored a complete conversion (direction +
# playbook/tool family — see ai_brain.ecu.sovereign_conversion, the single
# owner of that definition), the Brain is the constitutional opportunity
# authority: the legacy mechanical confidence tier becomes witness evidence
# (warning + telemetry) instead of a binary kill, and the qualification status
# floors at "candidate" so downstream authorities (council, regime, risk,
# trigger, FC-0B) finally get to EVALUATE the thesis instead of never seeing
# it. Bounded like AB-7.3c: the floor only raises the status tier, never
# fabricates the opportunity score, never touches environment-danger
# disqualifiers, and requires the qualification direction to be the Brain's.
# On ANY degraded Brain source the predicate fails closed and this whole block
# is inert — today's legacy behavior, byte-for-byte.
_BRAIN_CONVERSION_FLOOR = "candidate"


def _brain_sovereignty(snapshot: dict) -> tuple:
    """(sovereign, detail) via the ECU-owned predicate. Fails CLOSED."""
    try:
        from ai_brain.ecu import sovereign_conversion
        return sovereign_conversion(snapshot)
    except Exception as exc:  # noqa: BLE001
        return False, f"sovereignty_unavailable:{exc}"


def _apply_brain_conversion_floor(status: str, direction: str,
                                  disqualified: bool, thesis: dict,
                                  sovereign: bool) -> tuple:
    """Return (status, floor_applied). Floors a sovereign Brain conversion at
    candidate so it survives to the downstream authorities. Never floors a
    hard-disqualified environment or a direction the Brain didn't author."""
    if not sovereign or disqualified:
        return status, False
    if direction != (thesis or {}).get("direction"):
        return status, False
    if _STATUS_ORDER.index(status) < _STATUS_ORDER.index(_BRAIN_CONVERSION_FLOOR):
        return _BRAIN_CONVERSION_FLOOR, True
    return status, False


# ── Hard Disqualifiers ────────────────────────────────────────────────────────

def _is_disqualified(ai_context: dict, volatility: dict,
                     demote_conf_tier: bool = False,
                     demote_volatility: bool = False,
                     demote_narrative: bool = False) -> "tuple[bool, str | None]":
    """
    Returns (disqualified, reason). The boolean is byte-identical to the prior
    behavior; the reason NAMES the specific hard disqualifier so a READY setup
    is never silently reported as "no opportunity identified" when the true
    cause is an environmental danger refusal (HOSTILE-AUDIT, 2026-07-08).

    The exception clause prevents auto-disqualification when only 15m is toxic
    and lower timeframes remain healthy.

    AI-AUTH-2: `demote_conf_tier` is True only when the healthy LLM Brain
    authored a complete conversion — the legacy confidence tier then becomes
    witness evidence instead of a binary kill. Environment-danger checks
    (no-trade narratives, dangerous state, multi-TF toxicity) keep full
    authority regardless: they judge safety, not opportunity.
    """
    market_state = ai_context.get("market_state", "")
    conf_tier    = ai_context.get("confidence_tier", "")
    narrative    = ai_context.get("market_narrative", "")

    # AI_CONTEXT-AUTHORITY (2026-07-09) — market_narrative is MECHANICALLY authored
    # (build_narrative reads structure/vol/expansion/liquidity/po3, no Brain input).
    # When the Brain holds a sovereign directional conversion it may not hard-
    # disqualify; the would_have_disqualified telemetry is recorded by the caller.
    # demote_narrative is False by default and when the Brain is degraded/absent —
    # the mechanical narrative stays a live safety net there.
    if narrative in _NO_TRADE_NARRATIVES and not demote_narrative:
        return True, f"no_trade_narrative:{narrative}"

    # NOTE: control flow below is byte-identical to the pre-HOSTILE-AUDIT
    # version — the conf_tier check stays FIRST so no verdict changes (moving
    # the danger checks ahead would flip one input: conf_tier=no_trade with a
    # dangerous state + healthy 5m/3m safe harbor, which must stay disqualified).
    # We only ENRICH the reason: when the tier is no_trade, name the underlying
    # environmental danger if present, since a dangerous state caps confidence
    # at 49 (_apply_caps) and thus makes the tier a downstream echo.
    if conf_tier == "no_trade" and not demote_conf_tier:
        return True, _tier_no_trade_root_reason(market_state, volatility)

    # ── VOL-AUTH-1 — volatility disqualifiers (dangerous state, multi-TF toxic)
    # In observe_only mode these are DEMOTED: volatility may not zero
    # qualification. The would_have_vetoed telemetry is recorded by qualify_trade
    # via the shared volatility oracle. Default 'enforce' keeps them byte-
    # identical. Non-volatility disqualifiers above (no_trade narrative,
    # confidence tier) are unaffected — they judge opportunity, not volatility.
    if market_state == "dangerous":
        vol_5m = volatility.get("5m", {}).get("state", "")
        vol_3m = volatility.get("3m", {}).get("state", "")
        # Bypass disqualification if only 15m is toxic
        if vol_5m in ("stable", "expanding") and vol_3m in ("stable", "expanding"):
            return False, None
        if not demote_volatility:
            return True, "dangerous_market_state_no_lower_tf_safe_harbor"

    # Multiple HTFs toxic (15m + 5m)
    if not demote_volatility:
        toxic = sum(
            1 for tf in ["15m", "5m"]
            if volatility.get(tf, {}).get("state") in ("toxic", "explosive")
        )
        if toxic >= 2:
            return True, "multi_timeframe_toxic_volatility(15m+5m)"

    return False, None


def _tier_no_trade_root_reason(market_state: str, volatility: dict) -> str:
    """Name the ROOT cause behind a no_trade confidence tier: a dangerous state
    or multi-TF toxicity caps confidence at 49, so the tier is an echo. Reports
    the environmental danger when present; otherwise the tier itself (a
    genuinely weak-confidence environment)."""
    toxic = sum(
        1 for tf in ["15m", "5m"]
        if (volatility.get(tf, {}) or {}).get("state") in ("toxic", "explosive")
    )
    if market_state == "dangerous":
        return "confidence_tier_no_trade(dangerous_market_state)"
    if toxic >= 2:
        return "confidence_tier_no_trade(multi_timeframe_toxic_volatility)"
    return "confidence_tier_no_trade"


# ── Opportunity Score Components ──────────────────────────────────────────────

def _narrative_pts(ai_context: dict) -> int:
    return NARRATIVE_QUALITY.get(ai_context.get("market_narrative", ""), 3)


def _po3_pts(po3: dict) -> int:
    return PO3_ALIGNMENT_QUALITY.get(po3.get("alignment", ""), 4)


def _confidence_pts(ai_context: dict) -> int:
    """Scale 0-100 confidence score to 0-20 pts."""
    return round(ai_context.get("confidence_score", 0) / 100 * 20)


def _structure_pts(structure: dict) -> int:
    return STRUCTURE_ALIGNMENT_QUALITY.get(structure.get("alignment", "neutral"), 0)


def _memory_pts(memory: dict) -> int:
    """10 pts max — based on confidence trend and PO3 stability."""
    if not memory or not memory.get("available"):
        return 5  # no history — neutral credit

    g    = memory.get("global",     {}) or {}
    tfs  = memory.get("timeframes", {}) or {}
    pts  = 5
    trend = g.get("confidence_trend", "stable")

    if trend == "rising":
        pts += 3
    elif trend == "falling":
        pts -= 3

    # Stable HTF phase bonus — up to +2
    stable_htf = sum(
        1 for tf in ["15m", "5m"]
        if tfs.get(tf, {}).get("po3_stability_count", 0) >= 3
        and tfs.get(tf, {}).get("stable_po3_phase") in ("distribution", "manipulation", "accumulation")
    )
    pts += min(stable_htf, 2)

    # Flickering penalty (multiple HTFs changed phase and have low stability)
    flickering = sum(
        1 for tf in TIMEFRAMES
        if tfs.get(tf, {}).get("po3_phase_changed")
        and tfs.get(tf, {}).get("po3_stability_count", 0) <= 1
    )
    if flickering >= 2:
        pts -= 3

    return max(0, min(10, pts))


def _liquidity_pts(liquidity: dict) -> int:
    """10 pts max — quality of liquidity event."""
    tfs     = TIMEFRAMES
    sweep   = any(liquidity.get(tf, {}).get("sweep_detected")  for tf in tfs)
    reclaim = any(liquidity.get(tf, {}).get("reclaim_detected") for tf in tfs)
    failed  = any(liquidity.get(tf, {}).get("failed_breakout") for tf in ["5m", "3m", "1m"])

    if sweep and reclaim:
        return 10
    if failed:
        return 8
    if sweep:
        return 5
    return 3  # no event — stability credit


def _opportunity_score(snapshot: dict) -> int:
    ai_ctx    = snapshot.get("ai_context", {})
    po3       = snapshot.get("po3", {})
    structure = snapshot.get("structure", {})
    liquidity = snapshot.get("liquidity", {})
    memory    = snapshot.get("memory", {})

    raw = (
        _narrative_pts(ai_ctx)
        + _po3_pts(po3)
        + _confidence_pts(ai_ctx)
        + _structure_pts(structure)
        + _memory_pts(memory)
        + _liquidity_pts(liquidity)
    )
    return max(0, min(100, raw))


# ── Direction ─────────────────────────────────────────────────────────────────

def _direction_conflict_enabled() -> bool:
    """Phase FC-0A — June 11 direction-conflict veto. Rollback: env false."""
    return os.getenv("DIRECTION_CONFLICT_VETO", "true").lower().strip() == "true"


def _sweep_semantic_direction(liquidity: dict) -> "str | None":
    """
    Phase FC-0A — ICT sweep semantics on the highest timeframe with a
    confirmed sweep + reclaim:
      below_low  (sell stops raided, close back above) -> bullish delivery
      above_high (buy stops raided, close back below)  -> bearish delivery
    Same semantics as playbook_classifier._direction step 2 — which structure
    bias silently pre-empted on June 11.
    """
    for tf in TIMEFRAMES:
        liq = (liquidity or {}).get(tf, {}) or {}
        if liq.get("sweep_detected") and liq.get("reclaim_detected"):
            sweep_dir = liq.get("sweep_direction", "")
            if sweep_dir == "below_low":
                return "bullish"
            if sweep_dir == "above_high":
                return "bearish"
    return None


def _direction_with_source(ai_context: dict, structure: dict, po3: dict,
                           liquidity: "dict | None" = None,
                           brain_thesis: "dict | None" = None) -> tuple:
    """
    Phase AB-2A — returns (direction, direction_source).
    Firewall ON (default): structure bias is a WITNESS; only non-structure
    sources may author direction. Firewall OFF: legacy structure-rooted path.
    Phase AB-5B — ECU: when a Brain thesis is present it OWNS direction.
    """
    from generation_firewall.authorship import (
        firewall_enabled, authored_direction, SOURCE_LEGACY,
    )
    # Phase AB-5B — ECU: under BRAIN_ECU_MODE the Brain owns direction. The
    # mechanical firewall path becomes witness/fallback (used only when the
    # Brain thesis is non-directional).
    bt = (brain_thesis or {})
    if bt and bt.get("owner") == "ai_brain":
        bdir = (bt.get("direction") or "neutral").lower()
        if bdir in ("bullish", "bearish", "conflicted"):
            return bdir, "ai_brain"
        # Brain non-directional → fall through to mechanical witness below
    bias = ai_context.get("directional_bias", "neutral")
    if firewall_enabled():
        return authored_direction(bias, po3, liquidity or {})
    return _direction(ai_context, structure, po3, liquidity), SOURCE_LEGACY


def _direction(ai_context: dict, structure: dict, po3: dict,
               liquidity: "dict | None" = None) -> str:
    bias = ai_context.get("directional_bias", "neutral")

    if bias in ("bullish", "bearish"):
        # Phase FC-0A — sweep-semantics veto (June 11 root cause):
        # a confirmed sweep+reclaim whose ICT meaning contradicts the
        # structure bias is a direction conflict, not a tiebreak loss.
        if _direction_conflict_enabled():
            sweep_dir = _sweep_semantic_direction(liquidity or {})
            if sweep_dir is not None and sweep_dir != bias:
                return "conflicted"
        # Look for PO3 conflict
        po3_dir = (
            po3.get("15m", {}).get("distribution_direction")
            or po3.get("5m",  {}).get("distribution_direction")
        )
        if po3_dir and po3_dir not in (None, bias):
            return "conflicted"
        return bias

    if bias == "conflicted":
        return "conflicted"

    # Neutral bias — try to infer from PO3
    for tf in ["15m", "5m"]:
        d = po3.get(tf, {}).get("distribution_direction")
        if d in ("bullish", "bearish"):
            return d
    for tf in ["15m", "5m"]:
        m = po3.get(tf, {}).get("manipulation_direction")
        if m in ("bullish", "bearish"):
            return m

    # Infer from narrative label
    narrative = ai_context.get("market_narrative", "")
    if "bullish" in narrative:
        return "bullish"
    if "bearish" in narrative:
        return "bearish"

    return "neutral"


# ── Trade Type ────────────────────────────────────────────────────────────────

def _trade_type(ai_context: dict) -> str:
    narrative   = ai_context.get("market_narrative", "")
    personality = ai_context.get("trade_personality", "no_trade_context")

    _generic = {
        "neutral", "conflicted", "exhaustion_risk", "compression",
        "manipulation_without_distribution", "accumulation_before_expansion",
    }
    if narrative and narrative not in _generic:
        return narrative
    if personality != "no_trade_context":
        return personality
    return narrative or "no_trade_context"


# ── Status and Grade ──────────────────────────────────────────────────────────

def _status(score: int, disqualified: bool) -> str:
    if disqualified:
        return "no_trade"
    for threshold, label in STATUS_TIERS:
        if score >= threshold:
            return label
    return "no_trade"


def _grade(score: int, disqualified: bool) -> str:
    if disqualified:
        return "F"
    for threshold, label in GRADE_MAP:
        if score >= threshold:
            return label
    return "F"


# ── Reasons ───────────────────────────────────────────────────────────────────

def _reasons(snapshot: dict, direction: str) -> list:
    r          = []
    ai_context = snapshot.get("ai_context", {})
    structure  = snapshot.get("structure", {})
    liquidity  = snapshot.get("liquidity", {})
    expansion  = snapshot.get("expansion", {})
    volatility = snapshot.get("volatility", {})
    po3        = snapshot.get("po3", {})
    memory     = snapshot.get("memory", {})

    narrative = ai_context.get("market_narrative", "")
    po3_align = po3.get("alignment", "")
    alignment = structure.get("alignment", "neutral")

    # Lead with the narrative driver
    if narrative and narrative not in _NO_TRADE_NARRATIVES:
        r.append(f"Narrative: {narrative.replace('_', ' ')}")

    # Structure
    if alignment in ("full", "strong"):
        r.append(f"MTF structure alignment: {alignment}")
    for tf in ["15m", "5m"]:
        if structure.get(tf, {}).get("bos"):
            r.append(f"{tf} break of structure confirmed")
            break
    for tf in ["15m", "5m"]:
        if structure.get(tf, {}).get("mss"):
            r.append(f"{tf} market structure shift detected")
            break

    # Liquidity event
    for tf in TIMEFRAMES:
        liq = liquidity.get(tf, {})
        if liq.get("sweep_detected") and liq.get("reclaim_detected"):
            r.append(f"Liquidity sweep + reclaim confirmed on {tf}")
            break
    for tf in ["5m", "3m", "1m"]:
        if liquidity.get(tf, {}).get("failed_breakout"):
            r.append(f"Failed breakout detected on {tf}")
            break

    # PO3
    if po3_align == "manipulation_to_distribution":
        r.append("PO3 manipulation transitioning to distribution")
    elif po3_align == "full_distribution_alignment":
        r.append("PO3 full distribution alignment across timeframes")
    elif po3_align == "accumulation_building":
        r.append("PO3 accumulation building on higher timeframes")

    # Expansion
    for tf in ["15m", "5m"]:
        state = expansion.get(tf, {}).get("state", "")
        if state == "healthy_expansion":
            r.append(f"{tf} healthy expansion in progress")
            break
        if state == "mature_expansion":
            r.append(f"{tf} mature expansion detected")
            break

    if any(expansion.get(tf, {}).get("displacement_detected") for tf in ["15m", "5m"]):
        r.append("Displacement candle confirmed on higher timeframe")

    # Volatility — only mention when healthy
    vol_state = volatility.get("15m", {}).get("state", "")
    if vol_state in ("expanding", "stable"):
        r.append(f"15m volatility {vol_state} — healthy environment")

    # Memory
    if memory and memory.get("available"):
        g    = memory.get("global", {}) or {}
        tfs  = memory.get("timeframes", {}) or {}
        if g.get("confidence_trend") == "rising":
            r.append(f"Confidence rising +{g.get('confidence_delta', 0)} from prior snapshot")
        for tf in ["15m", "5m"]:
            count = tfs.get(tf, {}).get("po3_stability_count", 0)
            phase = tfs.get(tf, {}).get("stable_po3_phase", "")
            if count >= 3 and phase in ("distribution", "manipulation"):
                r.append(f"{tf} PO3 {phase} held stable for {count} snapshots")
                break

    return r


# ── Warnings ──────────────────────────────────────────────────────────────────

def _qual_warnings(snapshot: dict, opportunity_score: int) -> list:
    w          = []
    ai_context = snapshot.get("ai_context", {})
    structure  = snapshot.get("structure", {})
    volatility = snapshot.get("volatility", {})
    expansion  = snapshot.get("expansion", {})
    po3        = snapshot.get("po3", {})
    memory     = snapshot.get("memory", {})

    po3_align = po3.get("alignment", "")

    # Volatility
    vol_15m = volatility.get("15m", {}).get("state", "")
    if vol_15m in ("toxic", "explosive"):
        w.append("15m volatility classified as toxic — elevated risk environment")
    elif vol_15m == "unstable":
        w.append("15m volatility unstable — expect choppy conditions")

    if volatility.get("15m", {}).get("range_acceleration", 1.0) > 1.5:
        w.append("Range accelerating rapidly on 15m — volatility expanding fast")

    # Expansion exhaustion
    for tf in ["15m", "5m"]:
        exp = expansion.get(tf, {})
        if exp.get("exhaustion_risk") == "high" or exp.get("state") == "exhaustion_risk":
            w.append(f"{tf} expansion showing high exhaustion risk")
            break
        if exp.get("exhaustion_risk") == "medium" and exp.get("state") == "mature_expansion":
            w.append(f"{tf} mature expansion with medium exhaustion risk")
            break

    # Structure vs expansion
    if structure.get("15m", {}).get("state") == "range_bound":
        if ai_context.get("market_narrative") in (
            "distribution_in_progress", "range_expansion",
            "bullish_continuation", "bearish_continuation",
        ):
            w.append("Expansion occurring inside range-bound 15m structure")

    # PO3 alignment quality
    if po3_align in ("mixed", "no_clear_alignment"):
        w.append(f"PO3 alignment is {po3_align} — delivery direction unclear")

    # Coherence
    coherence = ai_context.get("coherence", {})
    if coherence.get("structure_expansion_alignment") == "conflicted":
        w.append("Structure and expansion conflicted on 15m")
    ve = coherence.get("volatility_expansion_alignment", "")
    if ve in ("mismatched", "dangerous"):
        w.append(f"Volatility/expansion alignment: {ve}")

    # Memory
    if memory and memory.get("available"):
        g   = memory.get("global", {}) or {}
        tfs = memory.get("timeframes", {}) or {}
        if g.get("confidence_trend") == "falling":
            w.append("Confidence trend deteriorating across snapshots")
        changed = [
            tf for tf in ["15m", "5m"]
            if tfs.get(tf, {}).get("po3_phase_changed")
        ]
        if changed:
            w.append(f"PO3 phase recently changed on {', '.join(changed)} — needs confirmation")

    return w


# ── Primary Driver (for formatter) ────────────────────────────────────────────

def _primary_driver(snapshot: dict, po3_align: str) -> str:
    narrative = snapshot.get("ai_context", {}).get("market_narrative", "")
    if narrative in ("bullish_continuation_after_manipulation",
                     "bearish_continuation_after_manipulation"):
        return "manipulation-to-distribution with directional delivery"
    if narrative == "liquidity_sweep_reversal":
        return "confirmed liquidity sweep with reclaim"
    if narrative == "distribution_in_progress":
        return "active distribution across timeframes"
    if po3_align == "manipulation_to_distribution":
        return "PO3 manipulation-to-distribution transition"
    if po3_align == "full_distribution_alignment":
        return "PO3 full distribution alignment"
    alignment = snapshot.get("structure", {}).get("alignment", "")
    if alignment in ("full", "strong"):
        return f"{alignment} MTF structure alignment"
    return narrative.replace("_", " ") if narrative else "mechanical evidence convergence"


# ── Public Entry Point ────────────────────────────────────────────────────────

def qualify_trade(snapshot: dict) -> dict:
    """
    Reads the full assembled snapshot (including ai_context and memory)
    and returns a qualification verdict.
    """
    ai_context = snapshot.get("ai_context", {})
    structure  = snapshot.get("structure", {})
    volatility = snapshot.get("volatility", {})
    po3        = snapshot.get("po3", {})

    # AI-AUTH-2 — Brain opportunity sovereignty (healthy LLM + full conversion
    # only; fails closed to legacy on every degraded source).
    brain_sovereign, sovereignty_detail = _brain_sovereignty(snapshot)

    # VOL-AUTH-1 — volatility veto authority (observe_only demotes it to advisory)
    from volatility_authority.volatility_authority import (
        observe_only as _vol_observe_only, volatility_telemetry,
    )
    _vol_observe = _vol_observe_only()
    _vol_tel = volatility_telemetry(ai_context, volatility)

    from shared_context.mechanical_judges import (
        judges_telemetry_only, mechanical_context_witness,
    )
    # JUDGE-FREEZE — in telemetry_only the mechanical confidence tier may not
    # disqualify. AI_CONTEXT-AUTHORITY — when the Brain is sovereign the
    # MECHANICAL market_narrative (conflicted/exhaustion_risk/compression) may not
    # hard-disqualify either; both become witness-only. Telemetry is preserved.
    _demote_narrative = mechanical_context_witness(snapshot)
    disqualified, disqualifier_reason = _is_disqualified(
        ai_context, volatility,
        demote_conf_tier=(brain_sovereign or judges_telemetry_only()),
        demote_volatility=_vol_observe,
        demote_narrative=_demote_narrative)
    # would_have_disqualified telemetry for the demoted mechanical narrative
    narrative_would_have_disqualified = (
        ai_context.get("market_narrative") in _NO_TRADE_NARRATIVES)
    narrative_disqualifier_demoted = bool(
        narrative_would_have_disqualified and _demote_narrative)
    opp_score       = 0 if disqualified else _opportunity_score(snapshot)

    # QUAL-FLICKER-AUDIT (2026-07-08) — the 2026-07-08 flicker trial proved every
    # narrative/conf-tier hard-disqualified no_trade scan had a would-be
    # opportunity score of <=22 (max, across all 86 scans) — i.e. the
    # disqualifier NEVER masked a tradeable-threshold opportunity; the score was
    # genuinely low (choppy, indecisive market). This records the score that
    # WOULD apply absent the disqualifier so "is qualification hiding
    # opportunity?" is answerable every scan. Observability only; the verdict is
    # unchanged.
    opp_score_undisq = _opportunity_score(snapshot) if disqualified else opp_score
    disqualifier_masks_opportunity = bool(disqualified and opp_score_undisq >= 40)
    status          = _status(opp_score, disqualified)
    grade           = _grade(opp_score, disqualified)
    direction, direction_source = _direction_with_source(
        ai_context, structure, po3, snapshot.get("liquidity", {}),
        snapshot.get("brain_thesis"))

    # ── Phase AB-7.3c — qualification inherits stability from the persistent thesis.
    # The mechanical score above still computes every scan; the floor only prevents
    # a one-scan dip from collapsing the status while the thesis remains valid.
    mechanical_status = status
    status, thesis_floor_applied = _apply_thesis_floor(
        status, direction, disqualified, snapshot.get("thesis_state"))
    # AI-AUTH-2 — a sovereign Brain conversion survives qualification at
    # >= candidate; the mechanical verdict stays recorded above.
    status, brain_floor_applied = _apply_brain_conversion_floor(
        status, direction, disqualified, snapshot.get("brain_thesis"),
        brain_sovereign)
    trade_type      = _trade_type(ai_context)
    reasons         = _reasons(snapshot, direction)
    warnings        = _qual_warnings(snapshot, opp_score)
    primary_driver  = _primary_driver(snapshot, po3.get("alignment", ""))

    # AI-AUTH-2 — the demoted legacy tier is surfaced as WITNESS evidence.
    if brain_sovereign and ai_context.get("confidence_tier") == "no_trade":
        warnings = list(warnings) + [
            "AI-AUTH-2: legacy confidence tier no_trade (score="
            f"{ai_context.get('confidence_score')}) demoted to witness — "
            f"Brain conversion holds opportunity authority ({sovereignty_detail})"
        ]
    if brain_floor_applied:
        warnings = list(warnings) + [
            "AI-AUTH-2: qualification floored at candidate by sovereign Brain "
            f"conversion (mechanical status was {mechanical_status})"
        ]

    # AB-2A — structure conflict/lag surfaced as a WITNESS warning (not authority)
    structure_bias = ai_context.get("directional_bias", "neutral")
    if (direction_source in ("delivery_vs_structure_conflict", "structure_witness_only")
            and structure_bias in ("bullish", "bearish")):
        warnings = list(warnings) + [
            f"structure witness bias={structure_bias} did not author direction "
            f"(source={direction_source})"
        ]

    # ── HOSTILE-AUDIT (2026-07-08) — truthful no_trade reason ─────────────────
    # A hard disqualifier zeroes the score REGARDLESS of setup quality (by
    # design — it judges environment SAFETY, not opportunity). Surfacing the
    # SPECIFIC disqualifier keeps decision/risk from reporting the generic
    # "no opportunity identified" while a READY tool exists. Qualification runs
    # BEFORE the toolbox, so it cannot see tool readiness itself — the
    # tool-aware phrasing lives in decision_engine (post-toolbox). Verdict
    # unchanged; this is audit truth only.
    if disqualified and disqualifier_reason:
        warnings = list(warnings) + [f"hard disqualifier: {disqualifier_reason}"]

    # ── VOL-AUTH-1 — volatility authority audit + would_have_vetoed telemetry ──
    # In observe_only mode volatility never zeroes qualification; the warning
    # still shows and the veto it WOULD have cast is recorded. The raw
    # volatility warnings from _qual_warnings above are untouched (still visible).
    qualification_zeroed_by_volatility = bool(
        disqualified and not _vol_observe and _vol_tel["volatility_would_have_vetoed"]
        and disqualifier_reason and (
            "toxic" in disqualifier_reason or "dangerous" in disqualifier_reason)
    )
    if _vol_observe and _vol_tel["volatility_would_have_vetoed"]:
        warnings = list(warnings) + [
            "VOL-AUTH-1 observe_only: volatility WOULD have vetoed "
            f"({_vol_tel['volatility_veto_reason']}) — recorded, not enforced; "
            "qualification scored by non-volatility authorities"
        ]

    return {
        "status":            status,
        "grade":             grade,
        "direction":         direction,
        "direction_source":  direction_source,   # AB-2A
        "trade_type":        trade_type,
        "opportunity_score": opp_score,
        "primary_driver":    primary_driver,
        "reasons":           reasons,
        "warnings":          warnings,
        # HOSTILE-AUDIT — the specific hard disqualifier (None when qualified)
        "disqualifier_reason": disqualifier_reason if disqualified else None,
        # Phase AB-7.3c — thesis stability floor audit trail
        "mechanical_status":     mechanical_status,
        "thesis_floor_applied":  thesis_floor_applied,
        # AI-AUTH-2 — Brain opportunity sovereignty audit trail
        "brain_sovereign":               brain_sovereign,
        "brain_sovereignty_detail":      sovereignty_detail,
        "brain_conversion_floor_applied": brain_floor_applied,
        # VOL-AUTH-1 — volatility authority audit block
        "volatility_authority":              _vol_tel["volatility_authority"],
        "volatility_would_have_vetoed":      _vol_tel["volatility_would_have_vetoed"],
        "volatility_veto_reason":            _vol_tel["volatility_veto_reason"],
        "volatility_effect_on_score":        _vol_tel["volatility_effect_on_score"],
        "qualification_zeroed_by_volatility": qualification_zeroed_by_volatility,
        # QUAL-FLICKER-AUDIT — is the hard disqualifier masking real opportunity?
        "opportunity_score_undisqualified":  opp_score_undisq,
        "disqualifier_masks_opportunity":    disqualifier_masks_opportunity,
        # AI_CONTEXT-AUTHORITY (2026-07-09) — mechanical narrative demotion audit
        "narrative_would_have_disqualified": narrative_would_have_disqualified,
        "narrative_disqualifier_demoted":    narrative_disqualifier_demoted,
    }
