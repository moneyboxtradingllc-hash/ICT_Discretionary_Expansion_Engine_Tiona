"""
MARKET COMMANDER — Layer 1 (Environment Intelligence) + Layer 2 (Participation Governor).

This is the adjudication architecture from the Architecture Review Board submission.
It does NOT count points and take the largest pile. It ADJUDICATES:

  Stage 0  Domain isolation     — Layer 1 is account-blind and setup-blind. It
                                  refuses qualification, opportunity score, playbook,
                                  risk, P&L, position, execution-gate and trade
                                  authorization at the door.
  Stage 1  Witness qualification — every evidence stream is judged for presence,
                                  freshness, self-confidence and coherence BEFORE its
                                  testimony is weighed. Missing evidence lowers
                                  completeness; it never disappears silently.
  Stage 2  Guardian veto tier   — NEWS_CHAOS / LIQUIDITY_VACUUM (HOSTILE) and
                                  DEAD_MARKET (INERT) are pre-score guardians, not
                                  contestants. A fired guardian forces the environment
                                  and a Layer 2 STAND_DOWN. It cannot be outvoted.
  Stage 3  Witness → family pressure — each witness pushes continuous, signed pressure
                                  onto environment FAMILIES, not single labels.
  Stage 4  Family-first resolution — the family is chosen first, the member second,
                                  so DIRECTIONAL siblings cannot cannibalise each other.
  Stage 5  Confidence / conflict / completeness synthesis — confidence is bounded by
                                  completeness (you cannot be more certain than you are
                                  informed); a lone loud witness can never be confident.
  Stage 6  Explainability record — supporting + contradicting evidence, scorecards,
                                  confidence breakdown, and a counterfactual flip.

Layer 2 is a four-gate Participation Governor that consumes ONLY the Layer 1 verdict.
Gates (all explicit and auditable): Environment, Confidence, Completeness, Conflict.
PARTICIPATE requires DIRECTIONAL family AND all four gates pass. Qualification may
only DOWNGRADE a participate verdict, never upgrade one.

OBSERVE-ONLY. authority_level is always "observe_only". It authorizes nothing,
blocks nothing, overrides nothing. Deterministic; never raises.
"""
from __future__ import annotations

import os

AUTHORITY_LEVEL = "observe_only"
SOURCE_AI = "AI_AUTHORED"
SOURCE_DETERMINISTIC = "DETERMINISTIC_FALLBACK"

# ── Environment families & members ─────────────────────────────────────────────
FAM_DIRECTIONAL = "DIRECTIONAL"
FAM_ROTATIONAL = "ROTATIONAL"
FAM_TRANSITIONAL = "TRANSITIONAL"
FAM_INERT = "INERT"
FAM_HOSTILE = "HOSTILE"
FAM_UNKNOWN = "UNKNOWN"

FAMILIES = frozenset({FAM_DIRECTIONAL, FAM_ROTATIONAL, FAM_TRANSITIONAL,
                      FAM_INERT, FAM_HOSTILE, FAM_UNKNOWN})

FAMILY_MEMBERS = {
    FAM_DIRECTIONAL: ("EXPANSION_TREND", "TREND_CONTINUATION", "MATURE_EXPANSION"),
    FAM_ROTATIONAL: ("RANGE_ROTATION", "CONSOLIDATION"),
    FAM_TRANSITIONAL: ("ACCUMULATION", "DISTRIBUTION", "REVERSAL_ATTEMPT"),
    FAM_INERT: ("DEAD_MARKET",),
    FAM_HOSTILE: ("NEWS_CHAOS", "LIQUIDITY_VACUUM"),
    FAM_UNKNOWN: ("UNKNOWN",),
}
MEMBER_TO_FAMILY = {m: fam for fam, members in FAMILY_MEMBERS.items() for m in members}

ENVIRONMENT_TYPES = frozenset(MEMBER_TO_FAMILY.keys())

# ── L2 enums ──────────────────────────────────────────────────────────────────
PARTICIPATION_DECISIONS = frozenset({"PARTICIPATE", "OBSERVE", "STAND_DOWN"})
FINAL_STATES = frozenset({
    "COMMAND_PARTICIPATE", "COMMAND_OBSERVE", "COMMAND_STAND_DOWN",
})

# Cognitive override statuses
OVERRIDE_AGREES = "AGREES_WITH_REGIME"
OVERRIDE_ACTIVE = "COGNITIVE_OVERRIDE_ACTIVE"
OVERRIDE_UNCLEAR = "UNCLEAR_LOW_CONFIDENCE"

# ── EXPLICIT, AUDITABLE THRESHOLDS (Layer 2 gates + doctrine) ──────────────────
CONF_PARTICIPATE = 60        # Confidence gate: below this, no participation.
COMPLETENESS_PARTICIPATE = 55  # Completeness gate: below this, no participation.
CONFLICT_MAX = 34            # Conflict gate: above this, no participation.
CONF_LOW = 45                # Below this the read is "unclear / low confidence".
UNKNOWN_COMPLETENESS_FLOOR = 30  # UNKNOWN + below this completeness → STAND_DOWN.
FAMILY_FLOOR = 14            # Top family below this → UNKNOWN (too thin to commit).
CORROBORATION_TARGET = 3     # Independent supporting witnesses for full corroboration.

# Domain-isolation: market-domain only. Layer 1 must NEVER read these.
_FORBIDDEN_L1_KEYS = frozenset({
    "qualification", "opportunity_score", "playbook", "selected_playbook",
    "risk", "risk_state", "pnl", "daily_pnl", "position", "positions",
    "execution_gate", "trade_authorization", "regime_permissions", "account",
    "order", "orders", "sizing",
})

_GATE_WEIGHTS = {  # expected witnesses + their importance for completeness
    "regime": 1.0, "volatility": 0.9, "expansion": 1.0, "delivery": 0.9,
    "structure": 0.8, "liquidity": 0.7, "po3": 0.7, "narrative": 0.7,
    "session": 0.4, "council": 0.5, "lifecycle": 0.5, "cross_tf_alignment": 0.6,
}


def _mc_mode() -> bool:
    return (os.getenv("MARKET_COMMANDER_MODE", "false") or "").strip().lower() == "true"


def _to_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _avg(vals):
    nums = [v for v in vals if isinstance(v, (int, float))]
    return (sum(nums) / len(nums)) if nums else None


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _thesis_executable(s: dict) -> bool:
    """AI-AUTH-1 — reconnected dead witness. thesis_state exposes
    'thesis_status' (not 'status'); the lifecycle block nests the status under
    active_thesis. The old read matched neither key and could never fire."""
    ts = s.get("thesis_state") or {}
    if (ts.get("thesis_status") or "").upper() == "EXECUTABLE":
        return True
    at = (s.get("thesis_lifecycle") or {}).get("active_thesis") or {}
    return (at.get("status") or "").upper() == "EXECUTABLE"


# ── Stage 0: domain isolation ──────────────────────────────────────────────────

def _market_evidence_view(s: dict) -> dict:
    """Account-blind, setup-blind projection of the snapshot. Layer 1 only ever
    sees this view, so qualification / risk / P&L / position / execution can never
    contaminate situational awareness."""
    return {k: v for k, v in (s or {}).items() if k not in _FORBIDDEN_L1_KEYS}


def _expansion_metrics(view: dict):
    exp = view.get("expansion") or {}
    states, gated, deff, bdom, escore = [], [], [], [], []
    for _tf, d in exp.items():
        if not isinstance(d, dict):
            continue
        if d.get("state"):
            states.append(str(d["state"]).lower())
        if "magnitude_gated" in d:
            gated.append(bool(d.get("magnitude_gated")))
        for src, dst in ((d.get("directional_efficiency"), deff),
                         (d.get("body_dominance"), bdom),
                         (d.get("expansion_score"), escore)):
            f = _to_float(src)
            if f is not None:
                dst.append(f)
    return states, gated, deff, bdom, escore


def _testimony(name, present, quality=0.0, pressures=None, observed="", signal="",
               missing_reason=""):
    return {"name": name, "present": bool(present),
            "quality": _clamp(float(quality), 0.0, 1.0) if present else 0.0,
            "pressures": pressures or {}, "observed": observed, "signal": signal,
            "missing_reason": missing_reason}


# ── Stage 1+3: witnesses (each returns one qualified testimony) ─────────────────

def _w_regime(view):
    mr = view.get("market_regime") or {}
    regime = (mr.get("regime_label") or "").lower()
    if not regime:
        return _testimony("regime", False, missing_reason="no market_regime.regime_label")
    fam = _regime_family(view)
    q = _clamp(_to_int(mr.get("confidence"), 60) / 100.0, 0.4, 0.95)
    # INERT/HOSTILE are guardian-only families — the regime label may *argue* for
    # them but it cannot win the competitive scorecard by itself (it is one field).
    competitive = fam not in (FAM_UNKNOWN, FAM_INERT, FAM_HOSTILE)
    return _testimony("regime", True, q, {fam: 20.0} if competitive else {},
                      observed=f"regime_label={regime}",
                      signal=f"mechanical regime argues {fam} (heaviest single witness)")


def _w_volatility(view):
    mr = view.get("market_regime") or {}
    vs = (mr.get("volatility_state") or "").lower()
    exp_state = (mr.get("expansion_state") or "").lower()
    if not (vs or exp_state):
        return _testimony("volatility", False, missing_reason="no volatility/expansion state")
    p, notes = {}, []
    if vs in ("low_volatility", "dead", "flat"):
        # Dead volatility is NOT a competitive vote; it is a corroboration input to
        # the DEAD_MARKET guardian (see _dead_supports). It cannot win on its own.
        notes.append("dead volatility (guardian input)")
    elif vs in ("toxic", "explosive", "high_volatility"):
        p[FAM_DIRECTIONAL] = p.get(FAM_DIRECTIONAL, 0) + 6
        p[FAM_TRANSITIONAL] = p.get(FAM_TRANSITIONAL, 0) + 4
        notes.append("volatile/unstable")
    if exp_state in ("healthy_expansion", "strong_expansion", "expanding", "mature_expansion"):
        p[FAM_DIRECTIONAL] = p.get(FAM_DIRECTIONAL, 0) + 14
        notes.append("expansion state")
    elif exp_state in ("compression", "compressed"):
        p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 12
        notes.append("compression state")
    return _testimony("volatility", True, 0.75, p,
                      observed=f"vol={vs or '?'} exp_state={exp_state or '?'}",
                      signal="; ".join(notes) or "neutral volatility")


def _w_expansion(view):
    states, gated, deff, bdom, escore = _expansion_metrics(view)
    if not (states or gated or deff or bdom or escore):
        return _testimony("expansion", False, missing_reason="no expansion telemetry")
    p, notes = {}, []
    strong = any(st in ("healthy_expansion", "strong_expansion", "expansion",
                        "expanding", "mature_expansion") for st in states)
    all_gated = bool(gated) and all(gated)
    compression = any(st in ("compression", "compressed", "exhausted") for st in states)
    ad, ab, ae = _avg(deff), _avg(bdom), _avg(escore)
    if strong and not all_gated:
        p[FAM_DIRECTIONAL] = p.get(FAM_DIRECTIONAL, 0) + 18
        notes.append("active displacement")
    if all_gated or compression:
        p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 12
        notes.append("gated/compressed")
    if ad is not None:
        if ad >= 0.6:
            p[FAM_DIRECTIONAL] = p.get(FAM_DIRECTIONAL, 0) + (ad - 0.5) * 16
            notes.append(f"dir_eff={ad:.2f}")
        elif ad <= 0.35:
            p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + (0.5 - ad) * 16
            notes.append(f"dir_eff={ad:.2f}")
    if ab is not None and ab < 0.45:
        p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 6
        notes.append(f"weak bodies={ab:.2f}")
    # quality scales with how much expansion telemetry exists
    q = _clamp(0.5 + 0.1 * len(view.get("expansion") or {}), 0.5, 0.9)
    return _testimony("expansion", True, q, p,
                      observed=f"states={states or '—'} dir_eff={ad} body={ab} score={ae}",
                      signal="; ".join(notes) or "flat expansion")


def _w_delivery(view):
    sc = view.get("shared_context") or {}
    ds = (sc.get("delivery_state") or "").lower()
    cont = sc.get("continuation_intact")
    exh = sc.get("exhaustion_present")
    if not ds and cont is None and exh is None:
        return _testimony("delivery", False, missing_reason="no shared_context delivery")
    p, notes = {}, []
    directional = ds not in ("", "unknown", "neutral", "none", "balanced") and any(
        k in ds for k in ("bull", "bear", "up", "down", "directional", "delivery", "continuation"))
    if directional and cont:
        p[FAM_DIRECTIONAL] = p.get(FAM_DIRECTIONAL, 0) + 14
        notes.append("directional delivery, continuation intact")
    if exh:
        p[FAM_TRANSITIONAL] = p.get(FAM_TRANSITIONAL, 0) + 10
        notes.append("delivery exhaustion")
    if cont is False or ds in ("", "unknown", "neutral", "none", "failed", "balanced"):
        p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 10
        notes.append("no/failed continuation")
    q = 0.9 if _to_float(sc.get("delivery_confidence")) else 0.8
    return _testimony("delivery", True, q, p,
                      observed=f"delivery_state={ds or '?'} continuation={cont} exhaustion={exh}",
                      signal="; ".join(notes) or "neutral delivery")


def _w_structure(view):
    st = view.get("structure") or {}
    if not st:
        return _testimony("structure", False, missing_reason="no structure block")
    align = str(st.get("alignment") or "").lower()
    states = [str(d["state"]).lower() for _tf, d in st.items()
              if isinstance(d, dict) and d.get("state")]
    text = " ".join(states + [align]).strip()
    if not text:
        return _testimony("structure", False, missing_reason="structure present but empty")
    p, notes = {}, []
    if "continuation" in text or "trend" in text or align in ("bullish", "bearish"):
        p[FAM_DIRECTIONAL] = p.get(FAM_DIRECTIONAL, 0) + 12
        notes.append("directional structure")
    if "range" in text or "neutral" in text or "balanced" in text:
        p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 10
        notes.append("range-bound structure")
    if "reversal" in text or "mss" in text:
        p[FAM_TRANSITIONAL] = p.get(FAM_TRANSITIONAL, 0) + 9
        notes.append("shift/reversal structure")
    return _testimony("structure", True, 0.7, p,
                      observed=f"alignment={align or '?'} states={states or '—'}",
                      signal="; ".join(notes) or "neutral structure")


def _w_liquidity(view):
    lq = view.get("liquidity") or {}
    draw = (view.get("narrative_authority") or {}).get("active_liquidity_draw")
    if not lq and not draw:
        return _testimony("liquidity", False, missing_reason="no liquidity evidence")
    swept = reclaim = buy = sell = False
    for _tf, d in lq.items():
        if not isinstance(d, dict):
            continue
        swept = swept or bool(d.get("sweep_detected"))
        reclaim = reclaim or bool(d.get("reclaim_detected"))
        buy = buy or bool(d.get("nearest_buy_side_liquidity") or d.get("nearest_buy"))
        sell = sell or bool(d.get("nearest_sell_side_liquidity") or d.get("nearest_sell"))
    p, notes = {}, []
    if swept and reclaim:
        p[FAM_TRANSITIONAL] = p.get(FAM_TRANSITIONAL, 0) + 9
        notes.append("sweep + reclaim")
    if buy and sell and not swept:
        p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 10
        notes.append("two-sided liquidity")
    if draw:
        p[FAM_DIRECTIONAL] = p.get(FAM_DIRECTIONAL, 0) + 8
        notes.append(f"one-sided draw={draw}")
    if not p:
        return _testimony("liquidity", False, missing_reason="liquidity inconclusive")
    return _testimony("liquidity", True, 0.65, p,
                      observed=f"sweep={swept} reclaim={reclaim} two_sided={buy and sell} draw={draw}",
                      signal="; ".join(notes))


def _w_po3(view):
    po3 = view.get("po3") or {}
    if not po3:
        return _testimony("po3", False, missing_reason="no po3 block")
    align = str(po3.get("alignment") or "").lower()
    p, notes = {}, []
    if "distribution" in align or "expansion" in align:
        p[FAM_DIRECTIONAL] = p.get(FAM_DIRECTIONAL, 0) + 8
        notes.append("PO3 distribution/expansion")
    elif "accumulation" in align:
        p[FAM_TRANSITIONAL] = p.get(FAM_TRANSITIONAL, 0) + 8
        notes.append("PO3 accumulation")
    elif align in ("", "no_clear", "mixed", "none", "neutral", "conflicted"):
        p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 8
        notes.append("PO3 unresolved")
    return _testimony("po3", True, 0.65, p, observed=f"alignment={align or '?'}",
                      signal="; ".join(notes) or "neutral po3")


def _w_session(view):
    sess = view.get("session")
    if isinstance(sess, dict):
        sess = sess.get("name") or sess.get("phase") or sess.get("label")
    sl = str(sess or "").lower()
    if not sl:
        return _testimony("session", False, missing_reason="no session context")
    p, notes = {}, []
    if any(k in sl for k in ("lunch", "midday")):
        p[FAM_ROTATIONAL] = 4
        p[FAM_INERT] = 3
        notes.append("lunch/midday drift")
    elif any(k in sl for k in ("after_hours", "overnight", "closed", "asia_dead")):
        p[FAM_INERT] = 5
        notes.append("thin session")
    elif any(k in sl for k in ("open", "ny_am", "london", "killzone", "_am")):
        p[FAM_DIRECTIONAL] = 4
        notes.append("active session")
    return _testimony("session", True, 0.5, p, observed=sl, signal="; ".join(notes) or "neutral session")


def _w_narrative(view):
    na = view.get("narrative_authority") or {}
    phase = str(na.get("narrative_phase") or "").lower()
    if not phase:
        return _testimony("narrative", False, missing_reason="no narrative phase")
    p, notes = {}, []
    if "continuation" in phase:
        p[FAM_DIRECTIONAL] = 8
        notes.append("narrative=continuation")
    elif "distribution" in phase:
        p[FAM_TRANSITIONAL] = 8
        notes.append("narrative=distribution")
    elif "accumulation" in phase:
        p[FAM_TRANSITIONAL] = 8
        notes.append("narrative=accumulation")
    elif "manipulation" in phase or "reversal" in phase:
        p[FAM_TRANSITIONAL] = 8
        notes.append("narrative=manipulation/reversal")
    elif phase in ("transition", "conflicted", "neutral", "rotational", "exhaustion"):
        p[FAM_ROTATIONAL] = 6
        notes.append(f"narrative={phase}")
    return _testimony("narrative", True, 0.7, p, observed=f"narrative_phase={phase}",
                      signal="; ".join(notes) or "neutral narrative")


def _w_council(view):
    cf = view.get("confidence_fusion") or {}
    if not cf:
        return _testimony("council", False, missing_reason="no confidence_fusion")
    status = str(cf.get("fusion_status") or "").lower()
    comb = _to_float(cf.get("combined_confidence"))
    p, notes = {}, []
    if comb is not None:
        if comb >= 70:
            p[FAM_DIRECTIONAL] = p.get(FAM_DIRECTIONAL, 0) + 5
            notes.append(f"consensus={comb:.0f}")
        elif comb <= 40:
            p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 5
            notes.append(f"weak consensus={comb:.0f}")
    if "conflict" in status or "diverg" in status:
        p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 5
        notes.append("council conflicted")
    elif "align" in status or "consensus" in status:
        p[FAM_DIRECTIONAL] = p.get(FAM_DIRECTIONAL, 0) + 4
        notes.append("council aligned")
    if not p:
        return _testimony("council", False, missing_reason="council inconclusive")
    return _testimony("council", True, 0.6, p,
                      observed=f"status={status or '?'} confidence={comb}", signal="; ".join(notes))


def _w_lifecycle(view):
    mm = view.get("market_memory") or {}
    trans = view.get("state_transition") or {}
    sl = view.get("setup_lifecycle") or {}
    flick = mm.get("flickering_tfs") or mm.get("flicker")
    tstate = str(trans.get("status") or trans.get("transition_state") or "").lower()
    lstate = str(sl.get("status") or "").lower()
    if not (flick or tstate or lstate):
        return _testimony("lifecycle", False, missing_reason="no lifecycle/transition signals")
    p, notes = {}, []
    if flick:
        p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 6
        notes.append("regime flicker")
    if "unstable" in tstate or "transition" in tstate:
        p[FAM_TRANSITIONAL] = p.get(FAM_TRANSITIONAL, 0) + 5
        notes.append(f"transition={tstate}")
    if lstate in ("invalidated", "failed", "expired"):
        p[FAM_TRANSITIONAL] = p.get(FAM_TRANSITIONAL, 0) + 5
        notes.append(f"setup {lstate}")
    return _testimony("lifecycle", True, 0.55, p,
                      observed=f"flicker={bool(flick)} transition={tstate or '?'} setup={lstate or '?'}",
                      signal="; ".join(notes) or "stable lifecycle")


def _w_cross_tf(view):
    """Meta-witness: dispersion across timeframes. Averaging hides conflict, so we
    measure DISAGREEMENT explicitly. Aligned TFs reinforce DIRECTIONAL; divergent
    TFs argue ROTATIONAL/TRANSITIONAL."""
    exp = view.get("expansion") or {}
    st = view.get("structure") or {}
    tf_states = []
    for block in (exp, st):
        for _tf, d in block.items():
            if isinstance(d, dict) and d.get("state"):
                tf_states.append(str(d["state"]).lower())
    if len(tf_states) < 2:
        return _testimony("cross_tf_alignment", False,
                          missing_reason="fewer than two timeframes to compare")
    directional = sum(1 for x in tf_states if any(
        k in x for k in ("expansion", "trend", "continuation", "bull", "bear")))
    rotational = sum(1 for x in tf_states if any(
        k in x for k in ("range", "compression", "neutral", "balanced", "consolid")))
    p, notes = {}, []
    if directional and rotational:
        p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 8
        notes.append("timeframes disagree (directional vs rotational)")
    elif directional and not rotational:
        p[FAM_DIRECTIONAL] = p.get(FAM_DIRECTIONAL, 0) + 8
        notes.append("timeframes aligned directional")
    elif rotational and not directional:
        p[FAM_ROTATIONAL] = p.get(FAM_ROTATIONAL, 0) + 6
        notes.append("timeframes aligned rotational")
    if not p:
        return _testimony("cross_tf_alignment", False, missing_reason="cross-tf inconclusive")
    return _testimony("cross_tf_alignment", True, 0.6, p,
                      observed=f"tf_states={tf_states}", signal="; ".join(notes))


_WITNESSES = (
    _w_regime, _w_volatility, _w_expansion, _w_delivery, _w_structure, _w_liquidity,
    _w_po3, _w_narrative, _w_session, _w_council, _w_lifecycle, _w_cross_tf,
)


# ── Stage 2: guardians (veto tier) ─────────────────────────────────────────────

DEAD_CONFIRM_SUPPORTS = 2   # independent supports required to CONFIRM a dead market.


def _dead_supports(view):
    """Independent, MARKET-DOMAIN-ONLY evidence that the tape is dead. (Account/
    setup signals such as 'no opportunity' are excluded by domain isolation.)
    Absence of a stream is never counted — only present evidence of deadness."""
    supports = []
    mr = view.get("market_regime") or {}
    regime = (mr.get("regime_label") or "").lower()
    vs = (mr.get("volatility_state") or "").lower()
    exp_state = (mr.get("expansion_state") or "").lower()
    states, gated, deff, _bdom, escore = _expansion_metrics(view)

    if regime in ("low_volatility", "dead") or vs in ("low_volatility", "dead", "flat"):
        supports.append("dead_regime_or_volatility")
    has_strong = any(st in ("healthy_expansion", "strong_expansion", "expansion",
                            "expanding", "mature_expansion") for st in states)
    if exp_state in ("compression", "compressed", "flat") or (states and not has_strong):
        supports.append("weak_or_absent_expansion")
    if gated and all(gated):
        supports.append("magnitude_gated_subfloor")
    ae = _avg(escore)
    if ae is not None and ae < 25:
        supports.append("subfloor_candle_movement")
    ad = _avg(deff)
    if ad is not None and ad <= 0.25:
        supports.append("low_directional_efficiency")
    sc = view.get("shared_context") or {}
    if ("delivery_state" in sc) or ("continuation_intact" in sc):
        ds = (sc.get("delivery_state") or "").lower()
        if ds in ("unknown", "none", "failed", "neutral") or sc.get("continuation_intact") is False:
            supports.append("no_or_failed_delivery")
    sess = view.get("session")
    if isinstance(sess, dict):
        sess = sess.get("name") or sess.get("phase") or sess.get("label")
    sl = str(sess or "").lower()
    if any(k in sl for k in ("lunch", "after_hours", "overnight", "closed", "asia_dead", "midday")):
        supports.append("inactive_session")
    return supports


def _guardian(view):
    """Return a guardian assessment. HOSTILE guardians (news / liquidity vacuum)
    fire on a single credible signal. The DEAD_MARKET (INERT) guardian requires
    corroboration: >= DEAD_CONFIRM_SUPPORTS independent supports CONFIRM it (then it
    cannot be outvoted); exactly one support marks it SUSPECTED (lower confidence,
    OBSERVE, scorecard continues). Guardians are never additive scorecard contestants."""
    nc = view.get("news_context") or {}
    if str(nc.get("risk_state", "")).lower() in ("high_risk", "stand_down", "red"):
        return {"kind": "veto", "family": FAM_HOSTILE, "member": "NEWS_CHAOS",
                "supports": [f"news_context.risk_state={nc.get('risk_state')}"]}
    mr = view.get("market_regime") or {}
    # `liquidity_vacuum` is a VOLATILITY state (volatility_classifier), never a
    # regime_label — classify_regime can only emit trend_up/trend_down/
    # range_rotation/chop/expansion_up/expansion_down/reversal_attempt/
    # high_volatility/low_volatility/unknown. Testing regime_label against it
    # meant this veto could never fire: a safety guardian that had never once
    # been reachable. market_regime carries volatility_state; that is the source.
    vol_state = (mr.get("volatility_state") or "").lower()
    if vol_state == "liquidity_vacuum" or view.get("liquidity_vacuum") is True:
        return {"kind": "veto", "family": FAM_HOSTILE, "member": "LIQUIDITY_VACUUM",
                "supports": [f"volatility_state={vol_state or 'flagged'}"]}
    # Deadness must be ANCHORED on low volatility/regime — compression with normal
    # volatility is a ROTATIONAL/CONSOLIDATION tape, not a dead one. The anchor plus
    # >= DEAD_CONFIRM_SUPPORTS total CONFIRMS; anchor alone SUSPECTS.
    dead = _dead_supports(view)
    if "dead_regime_or_volatility" not in dead:
        return None
    if len(dead) >= DEAD_CONFIRM_SUPPORTS:
        return {"kind": "veto", "family": FAM_INERT, "member": "DEAD_MARKET", "supports": dead}
    return {"kind": "suspected", "family": FAM_INERT, "member": "DEAD_MARKET", "supports": dead}


# ── Stage 4: member resolution within a family ─────────────────────────────────

def _resolve_member(family, view):
    members = FAMILY_MEMBERS[family]
    if len(members) == 1:
        return members[0], {members[0]: 100}
    states, gated, deff, bdom, escore = _expansion_metrics(view)
    mr = view.get("market_regime") or {}
    exp_state = (mr.get("expansion_state") or "").lower()
    regime = (mr.get("regime_label") or "").lower()
    sc = view.get("shared_context") or {}
    po3 = str((view.get("po3") or {}).get("alignment") or "").lower()
    na = str((view.get("narrative_authority") or {}).get("narrative_phase") or "").lower()
    scores = {m: 0 for m in members}

    if family == FAM_DIRECTIONAL:
        mature = exp_state == "mature_expansion" or "mature_expansion" in states or sc.get("exhaustion_present")
        fresh = (any(st in ("healthy_expansion", "strong_expansion", "expansion", "expanding")
                     for st in states) or exp_state in ("healthy_expansion", "strong_expansion")) \
            and not (bool(gated) and all(gated))
        scores["MATURE_EXPANSION"] += 30 if mature else 0
        scores["EXPANSION_TREND"] += 30 if fresh else 0
        scores["TREND_CONTINUATION"] += 20 if regime in ("trend_up", "trend_down") else 0
        scores["TREND_CONTINUATION"] += 12 if "continuation" in na else 0
        if not any(scores.values()):
            scores["TREND_CONTINUATION"] = 10
    elif family == FAM_ROTATIONAL:
        compression = exp_state in ("compression", "compressed") or (bool(gated) and all(gated))
        scores["CONSOLIDATION"] += 20 if compression else 0
        scores["RANGE_ROTATION"] += 20 if not compression else 8
        scores["CONSOLIDATION"] += 8 if regime in ("chop", "consolidation") else 0
    elif family == FAM_TRANSITIONAL:
        scores["ACCUMULATION"] += 20 if ("accumulation" in po3 or "accumulation" in na) else 0
        scores["DISTRIBUTION"] += 20 if ("distribution" in po3 or "distribution" in na
                                         or sc.get("exhaustion_present")) else 0
        scores["REVERSAL_ATTEMPT"] += 20 if ("reversal" in na or "manipulation" in na
                                             or regime == "reversal_attempt") else 0
        if not any(scores.values()):
            scores["REVERSAL_ATTEMPT"] = 10

    member = max(scores.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return member, {m: int(v) for m, v in scores.items()}


def _regime_family(view):
    """Map the regime read onto a family.

    Five of the values this tested against were unmatchable, borrowed from two
    other vocabularies: `accumulation` and `distribution` are PO3 PHASES,
    `liquidity_vacuum` is a VOLATILITY state, and `consolidation` and `dead` are
    emitted by nothing at all. regime_label can only ever be one of the ten
    labels classify_regime produces, so those branches were dead code.

    PO3 is NOT bridged in here. It already reaches family scoring through
    _w_po3, which maps distribution to DIRECTIONAL — routing the same phase to
    TRANSITIONAL here would have the two disagree about the same evidence.
    """
    mr = view.get("market_regime") or {}
    regime = (mr.get("regime_label") or "unknown").lower()
    vol_state = (mr.get("volatility_state") or "").lower()

    # Hostile first: a liquidity vacuum outranks whatever the trend read says.
    if vol_state == "liquidity_vacuum":
        return FAM_HOSTILE
    if regime in ("expansion_up", "expansion_down", "trend_up", "trend_down",
                  "high_volatility"):
        return FAM_DIRECTIONAL
    if regime in ("range_rotation", "chop"):
        return FAM_ROTATIONAL
    if regime == "reversal_attempt":
        return FAM_TRANSITIONAL
    if regime == "low_volatility":
        return FAM_INERT
    return FAM_UNKNOWN


# ── Stage 5+6: the full Layer-1 interpretation ─────────────────────────────────

def _interpret_environment(s: dict) -> dict:
    view = _market_evidence_view(s)

    # Stage 1: call every witness; record present + missing.
    testimonies = [fn(view) for fn in _WITNESSES]
    called = [t for t in testimonies if t["present"]]
    missing = [{"witness": t["name"], "reason": t["missing_reason"]}
               for t in testimonies if not t["present"]]

    # Evidence completeness — weighted fraction of credible witnesses that testified.
    total_w = sum(_GATE_WEIGHTS.values())
    have_w = sum(_GATE_WEIGHTS.get(t["name"], 0.5) * t["quality"] for t in called)
    completeness = int(round(100 * have_w / total_w)) if total_w else 0
    evidence_quality = int(round(100 * (_avg([t["quality"] for t in called]) or 0)))

    regime_fam = _regime_family(view)
    regime_input = (view.get("market_regime") or {}).get("regime_label") or "unknown"

    # Family scorecard from all testimony.
    fam_scores = {}
    for t in called:
        for fam, pts in t["pressures"].items():
            fam_scores[fam] = fam_scores.get(fam, 0) + pts

    # Stage 2: guardian assessment BEFORE choosing a family from the scorecard.
    guardian = _guardian(view)

    if guardian is not None and guardian["kind"] == "veto":
        family, member, supports = guardian["family"], guardian["member"], guardian["supports"]
        member_scorecard = {member: 100}
        conflict_index = 0
        # Confidence reflects the guardian's determination, still capped by completeness.
        confidence = min(80, max(completeness, 50))
        agrees = (regime_fam == family)
        breakdown = {"basis": "guardian_veto", "guardian_supports": supports,
                     "support_count": len(supports), "completeness": completeness,
                     "conflict_index": conflict_index, "ceiling_applied": completeness}
        supporting = [f"guardian confirmed by {len(supports)} witnesses: " + ", ".join(supports)]
        contradicting = [t["signal"] for t in called
                         if any(f not in (FAM_INERT, FAM_HOSTILE) for f in t["pressures"])][:6]
        counterfactual = (f"Guardian veto confirmed by {len(supports)} independent supports; "
                          f"structural and un-outvotable. Clears only if the {member} condition resolves.")
        return _verdict(family, member, confidence, completeness, conflict_index,
                        evidence_quality, regime_input, regime_fam, agrees,
                        _disagreement(agrees, family, regime_fam, supporting),
                        supporting, contradicting, [t["name"] for t in called],
                        missing, _round_scores(fam_scores), member_scorecard,
                        breakdown, counterfactual, _override_status(confidence, agrees),
                        dead_market_status=("CONFIRMED" if family == FAM_INERT else "CLEAR"),
                        guardian_confirmations=supports)

    # A single dead support → DEAD_MARKET SUSPECTED: do NOT force INERT; lower
    # confidence and let the scorecard continue (Layer 2 will OBSERVE, not STAND_DOWN).
    suspected_dead = guardian is not None and guardian["kind"] == "suspected"
    dead_supports = guardian["supports"] if guardian else []

    # Stage 4: family-first resolution. INERT/HOSTILE are guardian-only and never
    # compete in the scorecard, so a lone dead/hostile field cannot win by default.
    competitive = {f: sc for f, sc in fam_scores.items() if f not in (FAM_INERT, FAM_HOSTILE)}
    ranked = sorted(competitive.items(), key=lambda kv: (-kv[1], kv[0]))
    top_fam, top_score = (ranked[0] if ranked else (FAM_UNKNOWN, 0))
    second_fam, second_score = (ranked[1] if len(ranked) > 1 else (None, 0))

    if top_score < FAMILY_FLOOR:
        # Too thin to commit — UNKNOWN, not a guess.
        confidence = min(completeness, 30)
        breakdown = {"basis": "insufficient_family_pressure", "top_family_score": int(round(top_score)),
                     "family_floor": FAMILY_FLOOR, "completeness": completeness,
                     "dead_market_suspected": suspected_dead, "ceiling_applied": completeness}
        return _verdict(FAM_UNKNOWN, "UNKNOWN", confidence, completeness, 0,
                        evidence_quality, regime_input, regime_fam,
                        regime_fam in (FAM_UNKNOWN,),
                        ("dead market suspected — single unconfirmed support"
                         if suspected_dead else "evidence too thin to name a world"),
                        [t["signal"] for t in called][:4],
                        [], [t["name"] for t in called], missing,
                        _round_scores(fam_scores), {"UNKNOWN": 100}, breakdown,
                        ("A second independent dead support would CONFIRM DEAD_MARKET."
                         if suspected_dead else
                         "More credible witnesses (raise completeness) would name a family."),
                        OVERRIDE_UNCLEAR,
                        dead_market_status=("SUSPECTED" if suspected_dead else "CLEAR"),
                        guardian_confirmations=dead_supports)

    # Conflict index — opposing family pressure relative to the top.
    conflict_index = int(round(100 * second_score / (top_score + second_score))) \
        if (top_score + second_score) > 0 else 0

    member, member_scorecard = _resolve_member(top_fam, view)

    # Stage 5: confidence from corroboration × quality × (1−conflict) × margin,
    # CEILING-bound by completeness.
    supporters = [t for t in called if top_fam in t["pressures"]]
    corroboration = _clamp(len(supporters) / CORROBORATION_TARGET, 0.0, 1.0)
    sup_quality = _avg([t["quality"] for t in supporters]) or 0.0
    margin01 = _clamp((top_score - second_score) / (top_score + 1.0), 0.0, 1.0)
    conf_raw = 100 * (0.30 * corroboration + 0.25 * sup_quality
                      + 0.20 * (1 - conflict_index / 100.0)
                      + 0.15 * margin01 + 0.10 * (completeness / 100.0))
    # A suspected (unconfirmed) dead market injects uncertainty: discount confidence.
    dead_penalty = 0.7 if suspected_dead else 1.0
    confidence = int(round(min(conf_raw * dead_penalty, completeness)))  # CEILING: completeness

    breakdown = {
        "corroboration_witnesses": len(supporters),
        "corroboration_target": CORROBORATION_TARGET,
        "corroboration_factor": round(corroboration, 2),
        "supporting_witness_quality": round(sup_quality, 2),
        "conflict_index": conflict_index,
        "decisive_margin": round(margin01, 2),
        "completeness": completeness,
        "dead_market_suspected": suspected_dead,
        "raw_confidence": int(round(conf_raw)),
        "ceiling_applied": completeness,
        "ceiling_binding": conf_raw * dead_penalty > completeness,
    }

    agrees = (top_fam == regime_fam)
    supporting = [t["signal"] for t in supporters][:6]
    contradicting = [f"{t['name']}: {t['signal']}" for t in called
                     if any(f != top_fam for f in t["pressures"])][:6]
    needed = int(round(top_score - second_score)) + 1
    counterfactual = (
        f"If {second_fam} pressure rose by ~{needed} (e.g. a stronger "
        f"{(missing[0]['witness'] if missing else 'contradicting')} reading), the family "
        f"would flip from {top_fam} to {second_fam}." if second_fam else
        "No competing family present; a flip needs new contradicting evidence.")
    override_status = _override_status(confidence, agrees)

    return _verdict(top_fam, member, confidence, completeness, conflict_index,
                    evidence_quality, regime_input, regime_fam, agrees,
                    _disagreement(agrees, top_fam, regime_fam, supporting),
                    supporting, contradicting, [t["name"] for t in called], missing,
                    _round_scores(fam_scores), member_scorecard, breakdown,
                    counterfactual, override_status,
                    dead_market_status=("SUSPECTED" if suspected_dead else "CLEAR"),
                    guardian_confirmations=dead_supports)


def _round_scores(d):
    return {k: int(round(v)) for k, v in sorted(d.items(), key=lambda kv: -kv[1])}


def _override_status(confidence, agrees):
    if confidence < CONF_LOW:
        return OVERRIDE_UNCLEAR
    return OVERRIDE_AGREES if agrees else OVERRIDE_ACTIVE


def _disagreement(agrees, fam, regime_fam, supporting):
    if agrees:
        return None
    return (f"Commander interpreted {fam}; mechanical regime argued {regime_fam}. "
            f"Decisive evidence: {'; '.join(supporting[:3])}")


def _verdict(family, member, confidence, completeness, conflict_index, evidence_quality,
             regime_input, regime_fam, agrees, disagreement_reason, supporting,
             contradicting, witnesses_called, witnesses_missing, family_scorecard,
             member_scorecard, confidence_breakdown, counterfactual, override_status,
             dead_market_status="CLEAR", guardian_confirmations=None):
    return {
        "family": family, "type": member,
        "confidence": int(_clamp(confidence, 0, 100)),
        "completeness": int(_clamp(completeness, 0, 100)),
        "conflict_index": int(_clamp(conflict_index, 0, 100)),
        "evidence_quality": int(_clamp(evidence_quality, 0, 100)),
        "mechanical_regime_input": regime_input,
        "regime_argued_family": regime_fam,
        "commander_vs_regime_status": override_status,
        "agrees_with_mechanical_regime": bool(agrees),
        "disagreement_reason": disagreement_reason,
        "dead_market_status": dead_market_status,        # CONFIRMED / SUSPECTED / CLEAR
        "guardian_confirmations": list(guardian_confirmations or []),
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "witnesses_called": witnesses_called,
        "witnesses_missing": witnesses_missing,
        "family_scorecard": family_scorecard,
        "member_scorecard": member_scorecard,
        "confidence_breakdown": confidence_breakdown,
        "counterfactual_flip_condition": counterfactual,
        # explainability alias kept for the older 'evidence' consumers
        "evidence": supporting,
    }


# ── Layer 2: four-gate Participation Governor ──────────────────────────────────

def _govern(environment: dict, s: dict):
    """Consume ONLY the Layer-1 verdict object (+ qualification, downgrade-only).
    Four independent, auditable gates. PARTICIPATE needs all four to pass."""
    fam = environment["family"]
    conf = environment["confidence"]
    comp = environment["completeness"]
    conflict = environment["conflict_index"]

    # Gate 1 — Environment
    if fam in (FAM_HOSTILE, FAM_INERT):
        env_gate = {"name": "environment", "passed": False,
                    "observed": fam, "rule": "HOSTILE/INERT → STAND_DOWN"}
    elif fam == FAM_UNKNOWN:
        env_gate = {"name": "environment", "passed": False, "observed": fam,
                    "rule": "UNKNOWN → OBSERVE, or STAND_DOWN below completeness floor"}
    elif fam == FAM_DIRECTIONAL:
        env_gate = {"name": "environment", "passed": True, "observed": fam,
                    "rule": "DIRECTIONAL is participate-eligible"}
    else:  # ROTATIONAL / TRANSITIONAL
        env_gate = {"name": "environment", "passed": False, "observed": fam,
                    "rule": "ROTATIONAL/TRANSITIONAL → OBSERVE (not participate-eligible)"}

    conf_gate = {"name": "confidence", "passed": conf >= CONF_PARTICIPATE,
                 "observed": conf, "threshold": CONF_PARTICIPATE,
                 "rule": f"confidence ≥ {CONF_PARTICIPATE}"}
    comp_gate = {"name": "completeness", "passed": comp >= COMPLETENESS_PARTICIPATE,
                 "observed": comp, "threshold": COMPLETENESS_PARTICIPATE,
                 "rule": f"completeness ≥ {COMPLETENESS_PARTICIPATE}"}
    conflict_gate = {"name": "conflict", "passed": conflict <= CONFLICT_MAX,
                     "observed": conflict, "threshold": CONFLICT_MAX,
                     "rule": f"conflict_index ≤ {CONFLICT_MAX}"}
    gates = [env_gate, conf_gate, comp_gate, conflict_gate]

    blockers = [g["name"] + "_gate" for g in gates if not g["passed"]]

    suspected_dead = environment.get("dead_market_status") == "SUSPECTED"

    # Decision
    if fam in (FAM_HOSTILE, FAM_INERT):
        decision = "STAND_DOWN"
        reason = f"{fam} environment ({environment['type']}); capital protected"
    elif fam == FAM_UNKNOWN:
        # Suspected (unconfirmed) dead market → OBSERVE the tape, do not STAND_DOWN.
        if suspected_dead:
            decision = "OBSERVE"
            reason = "DEAD_MARKET suspected (single unconfirmed support); observing"
        else:
            decision = "STAND_DOWN" if comp < UNKNOWN_COMPLETENESS_FLOOR else "OBSERVE"
            reason = ("Environment unknown and too little evidence to act"
                      if decision == "STAND_DOWN" else "Environment unknown; observing for clarity")
    elif all(g["passed"] for g in gates) and not suspected_dead:
        decision = "PARTICIPATE"
        reason = f"DIRECTIONAL {environment['type']} passed all four gates"
    else:
        decision = "OBSERVE"
        failed = ", ".join(blockers) or ("dead_market_suspected" if suspected_dead else "gate(s)")
        if suspected_dead:
            blockers.append("dead_market_suspected")
        reason = f"{fam} {environment['type']}; held at OBSERVE by {failed}"

    # Qualification may only DOWNGRADE a participate verdict, never upgrade.
    qual = s.get("qualification") or {}
    qstat = (qual.get("status") or "").lower()
    if decision == "PARTICIPATE" and qstat in ("", "no_trade"):
        decision = "OBSERVE"
        blockers.append("qualification_downgrade")
        reason += " | downgraded to OBSERVE: qualification not trade-ready"

    if decision == "PARTICIPATE":
        pconf = conf
    elif decision == "STAND_DOWN":
        pconf = max(60, min(95, 70 + len(blockers) * 5))
    else:
        pconf = max(40, min(75, conf))

    participation = {
        "decision": decision, "confidence": int(pconf), "reason": reason,
        "blockers": blockers,
        "consumed_environment_family": fam,
        "consumed_environment_type": environment["type"],
        "consumed_environment_confidence": conf,
        "consumed_conflict_index": conflict,
        "consumed_completeness": comp,
        "gates": gates,
    }
    return participation


# ── public dispatcher ─────────────────────────────────────────────────────────

def build_market_commander_matrix(snapshot: dict) -> dict:
    """Observe-only L1/L2 verdict. AI-authored environment when MARKET_COMMANDER_MODE
    is on and a valid Brain L1/L2 block is present; otherwise deterministic. Layer 2
    is always the deterministic four-gate governor."""
    try:
        s = snapshot or {}
        if _mc_mode():
            ai = _extract_ai_matrix(s)
            if ai is not None:
                m = _from_ai(ai, s)
                if m is not None:
                    return m
        return _build_deterministic(s)
    except Exception as exc:  # noqa: BLE001
        return _safe_matrix(f"builder_error:{type(exc).__name__}")


def _build_deterministic(s: dict) -> dict:
    environment = _interpret_environment(s)
    participation = _govern(environment, s)
    return _assemble(environment, participation, s, SOURCE_DETERMINISTIC, [])


# ── AI-authored L1 (gated); L2 governor stays deterministic ────────────────────

def _extract_ai_matrix(s: dict):
    for loc in (s.get("ai_market_commander"),
                (s.get("ai_brain", {}) or {}).get("ai_market_commander"),
                ((s.get("candidate_thesis", {}) or {}).get("brain_block", {}) or {}).get("ai_market_commander")):
        if isinstance(loc, dict):
            return loc
    return None


def _from_ai(ai: dict, s: dict):
    """The Brain authors the environment READ (family/member + evidence). The
    deterministic interpreter still computes completeness/conflict/scorecards (those
    are facts about the evidence, not opinions), and the four-gate governor — also
    deterministic — decides participation. Returns None on unusable input."""
    try:
        e = ai.get("environment", {}) or {}
        env = str(e.get("type", "")).upper()
        if env not in ENVIRONMENT_TYPES:
            return None
        det = _interpret_environment(s)
        fam = MEMBER_TO_FAMILY[env]
        ai_conf = _to_int(e.get("confidence"), det["confidence"])
        # Confidence still cannot exceed completeness (doctrine), even from the AI.
        confidence = int(min(ai_conf, det["completeness"]))
        agrees = (fam == det["regime_argued_family"])

        environment = dict(det)  # inherit the full evidence record …
        environment.update({                       # … but adopt the AI's read.
            "family": fam, "type": env, "confidence": confidence,
            "agrees_with_mechanical_regime": bool(
                e.get("agrees_with_mechanical_regime", agrees)),
            "disagreement_reason": e.get("disagreement_reason", det["disagreement_reason"]),
            "commander_vs_regime_status": _override_status(confidence, agrees),
        })
        if isinstance(e.get("evidence"), list) and e["evidence"]:
            environment["supporting_evidence"] = list(e["evidence"])
            environment["evidence"] = list(e["evidence"])

        coerced = []
        ai_decision = str((ai.get("participation") or {}).get("decision", "")).upper()
        participation = _govern(environment, s)
        if ai_decision == "PARTICIPATE" and participation["decision"] != "PARTICIPATE":
            coerced.append(f"AI_PARTICIPATE_OVERRULED_BY_GATES_{participation['decision']}")
        if fam in (FAM_HOSTILE, FAM_INERT) and ai_decision and ai_decision != "STAND_DOWN":
            coerced.append(f"FORCED_STAND_DOWN_{env}")

        m = _assemble(environment, participation, s, SOURCE_AI, coerced)
        ok, _ = validate_market_commander_matrix(m)
        return m if ok else None
    except Exception:  # noqa: BLE001
        return None


# ── assemble + consistency + final_state ───────────────────────────────────────

def _assemble(environment: dict, participation: dict, s: dict, source: str, coerced: list) -> dict:
    contradictions = list(coerced)
    if participation["decision"] == "STAND_DOWN" and _thesis_executable(s):
        contradictions.append("STAND_DOWN_WITH_EXECUTABLE_THESIS")
    valid = not contradictions
    final = {"PARTICIPATE": "COMMAND_PARTICIPATE", "OBSERVE": "COMMAND_OBSERVE",
             "STAND_DOWN": "COMMAND_STAND_DOWN"}[participation["decision"]]
    return {
        "authority_level": AUTHORITY_LEVEL,
        "source": source,
        "environment": environment,
        "participation": participation,
        "consistency": {"logical_state_valid": valid, "contradictions": contradictions},
        "final_state": final,
    }


# ── validator ─────────────────────────────────────────────────────────────────

def validate_market_commander_matrix(m: dict) -> tuple:
    errors = []
    if not isinstance(m, dict):
        return False, ["matrix_not_dict"]
    if m.get("authority_level") != "observe_only":
        errors.append("authority_level_not_observe_only")
    if m.get("source") not in (SOURCE_AI, SOURCE_DETERMINISTIC):
        errors.append("bad_source")
    env = m.get("environment", {}) or {}
    if env.get("type") not in ENVIRONMENT_TYPES:
        errors.append("bad_environment_type")
    if env.get("family") not in FAMILIES:
        errors.append("bad_environment_family")
    if MEMBER_TO_FAMILY.get(env.get("type")) != env.get("family"):
        errors.append("member_family_mismatch")
    for f in ("confidence", "completeness", "conflict_index"):
        if not isinstance(env.get(f), int):
            errors.append(f"{f}_not_int")
    if isinstance(env.get("confidence"), int) and isinstance(env.get("completeness"), int):
        if env["confidence"] > env["completeness"]:
            errors.append("confidence_exceeds_completeness")
    p = m.get("participation", {}) or {}
    if p.get("decision") not in PARTICIPATION_DECISIONS:
        errors.append("bad_participation_decision")
    for f in ("consumed_environment_family", "consumed_environment_type"):
        if f not in p:
            errors.append(f"participation_missing_{f}")
    if m.get("final_state") not in FINAL_STATES:
        errors.append("bad_final_state")
    if not isinstance((m.get("consistency", {}) or {}).get("contradictions"), list):
        errors.append("contradictions_not_list")
    return (not errors), errors


# ── formatter (scan output) ────────────────────────────────────────────────────

def format_market_commander_summary(m: dict) -> list:
    try:
        env, part, cons = m["environment"], m["participation"], m["consistency"]
        src = m.get("source", SOURCE_DETERMINISTIC)
        fam_top = ", ".join(f"{k}={v}" for k, v in list(env.get("family_scorecard", {}).items())[:3])
        lines = [
            f"MC Environment : {env['family']}/{env['type']}@{env['confidence']} | "
            f"complete={env['completeness']} conflict={env['conflict_index']} | "
            f"{env['commander_vs_regime_status']} | {src} | OBSERVE_ONLY",
            f"MC Families    : {fam_top}",
            f"MC Participation: {part['decision']}@{part['confidence']} | "
            f"gates[" + ",".join(f"{g['name']}:{'P' if g['passed'] else 'F'}" for g in part.get("gates", [])) + f"] | reason={part['reason']}",
        ]
        if not env.get("agrees_with_mechanical_regime") and env.get("disagreement_reason"):
            lines.append(f"MC Override    : {env['disagreement_reason']}")
        if cons["logical_state_valid"]:
            lines.append(f"MC L1/L2 State : VALID | final={m['final_state']}")
        else:
            lines.append("MC L1/L2 State : INVALID | contradiction=" + ", ".join(cons["contradictions"]))
        return lines
    except Exception:  # noqa: BLE001
        return ["MC Environment : (unavailable)"]


def _safe_matrix(reason: str) -> dict:
    env = {
        "family": FAM_UNKNOWN, "type": "UNKNOWN", "confidence": 0, "completeness": 0,
        "conflict_index": 0, "evidence_quality": 0, "mechanical_regime_input": "unknown",
        "regime_argued_family": FAM_UNKNOWN, "commander_vs_regime_status": OVERRIDE_UNCLEAR,
        "agrees_with_mechanical_regime": True, "disagreement_reason": None,
        "supporting_evidence": [reason], "contradicting_evidence": [],
        "witnesses_called": [], "witnesses_missing": [], "family_scorecard": {},
        "member_scorecard": {"UNKNOWN": 100}, "confidence_breakdown": {"basis": reason},
        "counterfactual_flip_condition": reason, "evidence": [reason],
    }
    part = {
        "decision": "STAND_DOWN", "confidence": 0, "reason": reason, "blockers": [reason],
        "consumed_environment_family": FAM_UNKNOWN, "consumed_environment_type": "UNKNOWN",
        "consumed_environment_confidence": 0, "consumed_conflict_index": 0,
        "consumed_completeness": 0, "gates": [],
    }
    return {
        "authority_level": AUTHORITY_LEVEL, "source": SOURCE_DETERMINISTIC,
        "environment": env, "participation": part,
        "consistency": {"logical_state_valid": True, "contradictions": []},
        "final_state": "COMMAND_STAND_DOWN",
    }
