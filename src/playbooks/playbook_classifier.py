"""
Playbook Classifier — selects the best-fitting discretionary playbook from existing evidence.
Reads pre-computed snapshot dicts only. No indicator recalculation here.
"""

from playbooks.playbook_library import eligible_tools, preferred_tools


def _judges_frozen() -> bool:
    """JUDGE-FREEZE (2026-07-09) — when mechanical judges are telemetry_only the
    mechanical confidence_tier may not nudge playbook scores (the Brain owns
    direction/playbook). Default active = legacy scoring, bit-for-bit unchanged."""
    try:
        from shared_context.mechanical_judges import judges_telemetry_only
        return judges_telemetry_only()
    except Exception:  # noqa: BLE001
        return False


def _mech_ctx_witness(snap: dict) -> bool:
    """AI_CONTEXT-AUTHORITY (2026-07-09) — when the Brain is sovereign the
    MECHANICAL ai_context.market_state may not DOWNGRADE the playbook. Default
    active / non-sovereign = legacy penalty applies, bit-for-bit unchanged."""
    try:
        from shared_context.mechanical_judges import mechanical_context_witness
        return mechanical_context_witness(snap)
    except Exception:  # noqa: BLE001
        return False


_TFS = ["15m", "5m", "3m", "1m"]

_SWEEP_NARRATIVES = {
    "liquidity_sweep_reversal",
    "bullish_continuation_after_manipulation",
    "bearish_continuation_after_manipulation",
}

# ── SESSION-PO3 phase coupling (LUNA-SESSION-PO3-AUTHORITY-1) ────────────────
# Two effects, both narrow:
#   1. `accumulation_building` bonuses may no longer be paid while the canonical
#      session phase is an unresolved accumulation family. The hard block lives
#      upstream, so these could no longer produce a trade -- but a scoring rule
#      that REWARDS a breakout playbook for balance is exactly backwards, and
#      leaving it would keep contradicting the doctrine in the ranking.
#      They are gated, not deleted: after the phase resolves they still mean
#      what they always meant.
#   2. After MANIPULATION_CONFIRMED the reversal families are PREFERRED. A
#      preference is a ranking, never a permission: mechanical sufficiency,
#      geometry and risk still decide, and no trade is manufactured (S7).
_UNRESOLVED_ACCUMULATION = frozenset({
    "ACCUMULATION_FORMING", "ACCUMULATION_ESTABLISHED", "REACCUMULATION",
    "EXCURSION_UNRESOLVED",
})
#: Points a phase-preferred family earns. Deliberately small: it reorders
#: near-ties, it does not overwhelm the evidence a playbook actually scored on.
PHASE_PREFERENCE_POINTS = 15


def _session_phase(snap: dict) -> str:
    return str(((snap or {}).get("session_po3") or {}).get("phase") or "")


def _accumulation_bonus_allowed(snap: dict) -> bool:
    """False while the canonical session phase is unresolved accumulation."""
    return _session_phase(snap) not in _UNRESOLVED_ACCUMULATION


def _phase_preference(snap: dict, playbook: str) -> int:
    prefs = ((snap or {}).get("session_po3") or {}).get("preferred_playbook_families")
    return PHASE_PREFERENCE_POINTS if playbook in (prefs or []) else 0


_NO_PLAYBOOK_RESULT = {
    "selected_playbook":   "no_playbook",
    "playbook_confidence": 0,
    "direction":           "neutral",
    "direction_source":    "fallback_none",   # AB-2A
    "origination":         "none",            # FINAL-SHOT audit
    "eligible_tools":      [],
    "preferred_tools":     [],
    "status":              "no_playbook",
    "reasons":             [],
    "warnings":            [],
}


# ── Individual Playbook Scorers ───────────────────────────────────────────────

def _score_liquidity_sweep_reversal(snap: dict) -> int:
    liq = snap.get("liquidity", {})
    po3 = snap.get("po3",       {})
    exp = snap.get("expansion", {})
    ai  = snap.get("ai_context", {})
    s = 0

    if any(liq.get(tf, {}).get("sweep_detected")  for tf in _TFS):  s += 30
    if any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS): s += 20
    if ai.get("market_narrative") in _SWEEP_NARRATIVES:              s += 15

    po3_align = po3.get("alignment", "")
    if po3_align == "manipulation_to_distribution":                   s += 15
    elif any(po3.get(tf, {}).get("phase") == "manipulation" for tf in _TFS): s += 8

    if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
           for tf in ["3m", "1m"]):                                  s += 10

    if not _judges_frozen() and ai.get("confidence_tier") != "no_trade": s += 5

    if ai.get("market_state") == "dangerous" and not _mech_ctx_witness(snap):                        s -= 20
    if ai.get("market_narrative") in ("conflicted", "exhaustion_risk"): s -= 15

    return max(0, min(100, s))


def _score_trend_continuation(snap: dict) -> int:
    ai     = snap.get("ai_context", {})
    struct = snap.get("structure",  {})
    exp    = snap.get("expansion",  {})
    po3    = snap.get("po3",        {})
    liq    = snap.get("liquidity",  {})
    s = 0

    bias = ai.get("directional_bias", "neutral")
    if bias in ("bullish", "bearish"):                                s += 25

    align_pts = {"full": 20, "strong": 15, "partial": 8, "mixed": 3, "neutral": 0}
    s += align_pts.get(struct.get("alignment", "neutral"), 0)

    po3_align = po3.get("alignment", "")
    if po3_align == "full_distribution_alignment":                    s += 20
    elif po3_align == "manipulation_to_distribution":                 s += 12
    elif any(po3.get(tf, {}).get("phase") == "distribution" for tf in _TFS): s += 8

    if any(exp.get(tf, {}).get("state") in ("healthy_expansion", "mature_expansion")
           for tf in ["15m", "5m"]):                                  s += 15

    if not _judges_frozen() and ai.get("confidence_tier") in ("valid_setup", "elite_setup"): s += 10

    # Bonus: no opposing sweep (clean trend, no manipulation noise)
    if not any(liq.get(tf, {}).get("sweep_detected") for tf in _TFS): s += 5

    if bias in ("conflicted", "neutral"):                             s -= 20
    if ai.get("market_narrative") in ("conflicted", "exhaustion_risk"): s -= 15
    if ai.get("market_state") == "dangerous" and not _mech_ctx_witness(snap):                         s -= 15

    return max(0, min(100, s))


def _score_manipulation_to_distribution(snap: dict) -> int:
    po3 = snap.get("po3",        {})
    liq = snap.get("liquidity",  {})
    exp = snap.get("expansion",  {})
    ai  = snap.get("ai_context", {})
    mem = snap.get("memory",     {})
    s = 0

    po3_align = po3.get("alignment", "")
    if po3_align == "manipulation_to_distribution":                   s += 35
    elif po3_align == "accumulation_building" and _accumulation_bonus_allowed(snap):
        s += 15

    if any(liq.get(tf, {}).get("sweep_detected") for tf in _TFS):   s += 20

    if any(po3.get(tf, {}).get("phase") in ("distribution", "transition")
           for tf in ["3m", "1m"]):                                   s += 15

    g = (mem.get("global") or {}) if mem and mem.get("available") else {}
    if g.get("confidence_trend") in ("rising", "stable"):            s += 10

    if any(po3.get(tf, {}).get("phase") in ("accumulation", "manipulation")
           for tf in ["15m", "5m"]):                                  s += 10

    if ai.get("market_state") == "dangerous" and not _mech_ctx_witness(snap):                        s -= 20
    if ai.get("market_narrative") in ("conflicted", "exhaustion_risk"): s -= 15

    return max(0, min(100, s))


def _score_failed_breakout_reversal(snap: dict) -> int:
    liq    = snap.get("liquidity",  {})
    struct = snap.get("structure",  {})
    vol    = snap.get("volatility", {})
    ai     = snap.get("ai_context", {})
    s = 0

    if any(liq.get(tf, {}).get("failed_breakout")   for tf in _TFS): s += 40
    if any(struct.get(tf, {}).get("mss")             for tf in _TFS): s += 20
    if any(struct.get(tf, {}).get("bos")             for tf in _TFS): s += 15
    if any(liq.get(tf, {}).get("reclaim_detected")   for tf in _TFS): s += 15

    if vol.get("15m", {}).get("state") not in ("toxic", "explosive"): s += 10

    if vol.get("15m", {}).get("state") in ("toxic", "explosive"):     s -= 20
    if ai.get("market_narrative") in ("conflicted", "exhaustion_risk"): s -= 15

    return max(0, min(100, s))


def _score_opening_drive(snap: dict) -> int:
    if snap.get("session") != "ny_open":
        return 0  # hard block — only valid at the open

    exp    = snap.get("expansion",  {})
    vol    = snap.get("volatility", {})
    struct = snap.get("structure",  {})
    ai     = snap.get("ai_context", {})
    s = 30  # session bonus

    if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
           for tf in ["1m", "3m", "5m"]):                             s += 20

    vol_state = vol.get("15m", {}).get("state", "")
    if vol_state == "expanding":                                       s += 15
    elif vol_state in ("stable", "unstable"):                          s += 8

    align_pts = {"full": 15, "strong": 12, "partial": 8, "mixed": 3, "neutral": 0}
    s += align_pts.get(struct.get("alignment", "neutral"), 0)

    if not _judges_frozen() and ai.get("confidence_tier") != "no_trade": s += 10

    if vol_state in ("toxic", "explosive"):                            s -= 20
    if ai.get("market_narrative") in ("conflicted", "exhaustion_risk"): s -= 15

    return max(0, min(100, s))


def _score_range_expansion(snap: dict) -> int:
    struct = snap.get("structure",  {})
    exp    = snap.get("expansion",  {})
    vol    = snap.get("volatility", {})
    po3    = snap.get("po3",        {})
    ai     = snap.get("ai_context", {})
    s = 0

    if struct.get("15m", {}).get("state") in ("range_bound", "neutral"): s += 20

    if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
           for tf in ["1m", "3m", "5m"]):                              s += 20

    vol_state = vol.get("15m", {}).get("state", "")
    if vol_state in ("expanding",) and vol_state != "toxic":           s += 15

    align = struct.get("alignment", "neutral")
    if align in ("neutral", "mixed", "partial"):                       s += 10
    elif align in ("full", "strong"):                                   s -= 15  # trending, not ranging

    if po3.get("alignment") == "manipulation_to_distribution":
        s += 10
    elif (po3.get("alignment") == "accumulation_building"
          and _accumulation_bonus_allowed(snap)):
        s += 10

    if ai.get("market_narrative") in ("conflicted", "exhaustion_risk"): s -= 15
    if ai.get("market_state") == "dangerous" and not _mech_ctx_witness(snap):                           s -= 15

    return max(0, min(100, s))


# ── Direction ─────────────────────────────────────────────────────────────────

def _direction(snap: dict) -> str:
    # 1. Use qualification direction if already directional
    qual_dir = snap.get("qualification", {}).get("direction", "neutral")
    if qual_dir in ("bullish", "bearish"):
        return qual_dir
    if qual_dir == "conflicted":
        return "conflicted"

    # AB-2A — Structure-Authorship Firewall:
    # When the firewall is ON and qualification did not hand us a direction,
    # the playbook may NOT re-author from structure (the ai_context bias step
    # below). It may only originate from non-structure authoring evidence
    # (delivery/sweep) via the shared firewall. This closes the structure
    # re-entry leak MAP-0 found at playbook _direction step 3.
    from generation_firewall.authorship import firewall_enabled, authored_direction
    if firewall_enabled():
        bias = snap.get("ai_context", {}).get("directional_bias", "neutral")
        d, _src = authored_direction(bias, snap.get("po3", {}), snap.get("liquidity", {}))
        return d

    # 2. Infer from sweep direction (most ICT-accurate inference)
    liq = snap.get("liquidity", {})
    for tf in _TFS:
        l = liq.get(tf, {})
        if l.get("sweep_detected") and l.get("reclaim_detected"):
            sd = l.get("sweep_direction", "")
            if sd == "below_low":
                return "bullish"    # swept sell stops → expect bullish delivery
            if sd == "above_high":
                return "bearish"    # swept buy stops → expect bearish delivery

    # 3. AI context bias
    bias = snap.get("ai_context", {}).get("directional_bias", "neutral")
    if bias in ("bullish", "bearish"):
        return bias

    # 4. PO3 distribution or manipulation direction
    po3 = snap.get("po3", {})
    for tf in _TFS:
        for key in ("distribution_direction", "manipulation_direction"):
            d = po3.get(tf, {}).get(key)
            if d in ("bullish", "bearish"):
                return d

    # 5. Narrative label inference
    narrative = snap.get("ai_context", {}).get("market_narrative", "")
    if "bullish" in narrative:
        return "bullish"
    if "bearish" in narrative:
        return "bearish"

    return "neutral"


# ── Status ────────────────────────────────────────────────────────────────────

def _status(score: int) -> str:
    if score >= 85:
        return "elite"
    if score >= 75:
        return "strong"
    if score >= 60:
        return "active"
    if score >= 45:
        return "forming"
    return "no_playbook"


# ── Reasons ───────────────────────────────────────────────────────────────────

def _reasons(playbook: str, snap: dict) -> list:
    r      = []
    liq    = snap.get("liquidity",  {})
    po3    = snap.get("po3",        {})
    exp    = snap.get("expansion",  {})
    struct = snap.get("structure",  {})
    vol    = snap.get("volatility", {})
    ai     = snap.get("ai_context", {})
    mem    = snap.get("memory",     {})

    if playbook == "liquidity_sweep_reversal":
        for tf in _TFS:
            l = liq.get(tf, {})
            if l.get("sweep_detected") and l.get("reclaim_detected"):
                r.append(f"Liquidity sweep + reclaim confirmed on {tf} ({l.get('sweep_direction','')})")
                break
        if po3.get("alignment") == "manipulation_to_distribution":
            r.append("PO3 manipulation-to-distribution sequence confirmed")
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["3m", "1m"]):
            r.append("Lower timeframe expansion beginning after reclaim")
        for tf in _TFS:
            if struct.get(tf, {}).get("mss"):
                r.append(f"Market structure shift detected on {tf}")
                break

    elif playbook == "trend_continuation":
        bias  = ai.get("directional_bias", "")
        align = struct.get("alignment", "")
        if bias in ("bullish", "bearish"):
            r.append(f"Directional bias confirmed: {bias}")
        if align in ("full", "strong"):
            r.append(f"MTF structure alignment: {align}")
        for tf in ["15m", "5m"]:
            state = exp.get(tf, {}).get("state", "")
            if state in ("healthy_expansion", "mature_expansion"):
                r.append(f"{tf} {state.replace('_', ' ')} in progress")
                break
        po3_align = po3.get("alignment", "")
        if po3_align in ("full_distribution_alignment", "manipulation_to_distribution"):
            r.append(f"PO3 alignment supports continuation: {po3_align}")

    elif playbook == "manipulation_to_distribution":
        r.append("PO3 manipulation-to-distribution alignment detected")
        if any(liq.get(tf, {}).get("sweep_detected") for tf in _TFS):
            r.append("Liquidity sweep involved in manipulation phase")
        if any(po3.get(tf, {}).get("phase") in ("distribution", "transition") for tf in ["3m", "1m"]):
            r.append("Lower timeframe distribution phase beginning")
        g = (mem.get("global") or {}) if mem and mem.get("available") else {}
        if g.get("confidence_trend") == "rising":
            r.append("Confidence rising — setup strengthening across snapshots")

    elif playbook == "failed_breakout_reversal":
        for tf in _TFS:
            if liq.get(tf, {}).get("failed_breakout"):
                r.append(f"Failed breakout detected on {tf}")
                break
        if any(struct.get(tf, {}).get("mss") for tf in _TFS):
            r.append("Market structure shift confirms reversal")
        if any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS):
            r.append("Price reclaimed prior level after failed breakout")

    elif playbook == "opening_drive":
        r.append("NY open session — early expansion window active")
        for tf in ["1m", "3m", "5m"]:
            state = exp.get(tf, {}).get("state", "")
            if state in ("early_expansion", "healthy_expansion"):
                r.append(f"{tf} expansion detected at open: {state}")
                break
        align = struct.get("alignment", "")
        if align in ("partial", "strong", "full"):
            r.append(f"Structure beginning to align at open: {align}")
        vol_state = vol.get("15m", {}).get("state", "")
        if vol_state in ("expanding",):
            r.append("Volatility expanding — open drive supported")

    elif playbook == "range_expansion":
        if struct.get("15m", {}).get("state") in ("range_bound", "neutral"):
            r.append("15m market in range-bound condition — expansion possible")
        for tf in ["1m", "3m", "5m"]:
            state = exp.get(tf, {}).get("state", "")
            if state in ("early_expansion", "healthy_expansion"):
                r.append(f"{tf} expansion beginning inside/out of range")
                break
        if vol.get("15m", {}).get("state") == "expanding":
            r.append("Volatility expanding — range breakout supported")

    return r


# ── Warnings ──────────────────────────────────────────────────────────────────

def _warnings(playbook: str, direction: str, snap: dict) -> list:
    w      = []
    vol    = snap.get("volatility", {})
    po3    = snap.get("po3",        {})
    struct = snap.get("structure",  {})
    ai     = snap.get("ai_context", {})
    mem    = snap.get("memory",     {})

    if direction in ("neutral", "conflicted"):
        w.append(f"Direction is {direction} — tool selection pending confirmation")

    vol_state = vol.get("15m", {}).get("state", "")
    if vol_state in ("toxic", "explosive"):
        w.append("15m volatility elevated — Risk Governor should reduce exposure")
    elif vol_state == "unstable":
        w.append("Volatility unstable — expect choppy delivery conditions")

    po3_align = po3.get("alignment", "")
    if po3_align in ("mixed", "no_clear_alignment"):
        w.append("PO3 alignment mixed — delivery confirmation still needed")

    align = struct.get("alignment", "neutral")
    if align in ("neutral", "mixed") and playbook in ("trend_continuation", "opening_drive"):
        w.append("Structure not fully aligned — continuation not yet confirmed")

    if playbook == "liquidity_sweep_reversal" and \
       po3_align not in ("manipulation_to_distribution", "full_distribution_alignment"):
        w.append("PO3 has not confirmed full manipulation-to-distribution sequence")

    if playbook in ("opening_drive", "range_expansion"):
        w.append("Expansion exists but structure has not fully confirmed — watch for false break")

    if mem and mem.get("available"):
        g = mem.get("global") or {}
        if g.get("confidence_trend") == "falling":
            w.append("Confidence trend deteriorating — setup quality declining")

    return w


# ── Public Entry Point ────────────────────────────────────────────────────────

def classify_playbook(snapshot: dict) -> dict:
    """
    Selects the highest-scoring playbook from the assembled snapshot.
    Returns no_playbook when qualification blocks or no playbook meets threshold.
    """
    # Score every playbook
    scorers = {
        "liquidity_sweep_reversal":    _score_liquidity_sweep_reversal,
        "trend_continuation":           _score_trend_continuation,
        "manipulation_to_distribution": _score_manipulation_to_distribution,
        "failed_breakout_reversal":     _score_failed_breakout_reversal,
        "opening_drive":                _score_opening_drive,
        "range_expansion":              _score_range_expansion,
    }
    scores = {name: fn(snapshot) for name, fn in scorers.items()}

    # SESSION-PO3 reversal priority. After MANIPULATION_CONFIRMED the reversal
    # families rank first into distribution. Ranking only -- the phase never
    # creates a playbook that scored nothing, and an empty opportunity set still
    # produces no trade.
    _prefs = ((snapshot or {}).get("session_po3") or {}).get(
        "preferred_playbook_families") or []
    if _prefs:
        scores = {name: min(100, sc + _phase_preference(snapshot, name)) if sc else sc
                  for name, sc in scores.items()}

    # ── Phase AB-5B — ECU: the Brain ORIGINATES the playbook ─────────────────
    # When the Brain asserts an opportunity and names a valid playbook family,
    # it originates the selection; the classifier becomes validator/ranker
    # (computes the score + eligible tools, but does not block on threshold or
    # qualification no_trade). Mechanical scoring resumes only when the Brain
    # does not name a valid playbook.
    _PHASE_TO_PLAYBOOK = {
        "manipulation": "liquidity_sweep_reversal",
        "reversal": "liquidity_sweep_reversal",
        "exhaustion": "liquidity_sweep_reversal",
        "continuation": "trend_continuation",
        "distribution": "manipulation_to_distribution",
    }
    bt = snapshot.get("brain_thesis") or {}
    if bt.get("owner") == "ai_brain" and bt.get("opportunity"):
        bfam = (bt.get("playbook_family") or "").lower().strip()
        bdir = _direction(snapshot)
        if bfam not in scorers:    # map the Brain's phase/family to a playbook key
            bfam = _PHASE_TO_PLAYBOOK.get((bt.get("opportunity_type") or "").lower().strip(), bfam)
        if bfam in scorers and bdir in ("bullish", "bearish"):
            return {
                "selected_playbook":   bfam,
                "playbook_confidence": max(int(bt.get("confidence", 0)), scores.get(bfam, 0)),
                "direction":           bdir,
                "direction_source":    "ai_brain",
                "origination":         "ai_brain_family",   # FINAL-SHOT audit
                "eligible_tools":      eligible_tools(bfam, bdir),
                "preferred_tools":     preferred_tools(bfam, bdir),
                "status":              _status(max(int(bt.get("confidence", 0)), scores.get(bfam, 0))),
                "reasons":             [f"Brain-originated playbook ({bfam})"],
                "warnings":            ["AB-5B: classifier is validator/ranker; Brain owns selection"],
            }

        # ── FINAL-SHOT — directional discovery ───────────────────────────────
        # 2026-07-07 14:32 defect: a HEALTHY LLM thesis (bearish@45, phase
        # "accumulation", family "none") fell through here into the
        # qualification hard block below, which returned no_playbook with a
        # MISLEADING warning and shut off the toolbox sensors — the real
        # bearish FVG retest was never scored, and no downstream authority
        # ever evaluated the thesis. Repair: when the healthy Brain authors
        # direction without a mappable family, attempt MECHANICAL DISCOVERY
        # using the scores already computed above at the EXISTING >=45
        # threshold (unchanged). A discovered playbook opens the toolbox
        # sensors so governance can evaluate real structure; it grants NO
        # sovereignty (AI-AUTH-2 still requires a Brain family conversion —
        # the mechanical layer may not author opportunity). Degraded/fallback
        # Brain sources fail closed via healthy_directional_thesis and keep
        # the legacy path below byte-identical.
        try:
            from ai_brain.ecu import healthy_directional_thesis
            _healthy, _hd_detail = healthy_directional_thesis(snapshot)
        except Exception:  # noqa: BLE001
            _healthy = False
        _tdir = bt.get("direction")
        if _healthy and _tdir in ("bullish", "bearish"):
            _phase = (bt.get("opportunity_type") or "none")
            _best = max(scores, key=scores.get)
            _best_score = scores[_best]
            if _best_score >= 45:   # existing mechanical threshold — unchanged
                return {
                    "selected_playbook":   _best,
                    "playbook_confidence": _best_score,
                    "direction":           _tdir,
                    "direction_source":    "ai_brain",
                    "origination":         "brain_directional_discovery",
                    "eligible_tools":      eligible_tools(_best, _tdir),
                    "preferred_tools":     preferred_tools(_best, _tdir),
                    "status":              _status(_best_score),
                    "reasons": [
                        f"Brain directional thesis ({_tdir}@{bt.get('confidence')}, "
                        f"phase='{_phase}') named no family — mechanical discovery "
                        f"selected {_best} at {_best_score}"],
                    "warnings": [
                        "FINAL-SHOT: playbook discovered mechanically for a "
                        "family-less Brain thesis; no sovereignty granted — "
                        "qualification/AI-AUTH-2 still require a Brain family "
                        "conversion"],
                }
            # discovery found nothing — return the TRUTHFUL audit trail
            result = _NO_PLAYBOOK_RESULT.copy()
            result["direction"]        = _tdir
            result["direction_source"] = "ai_brain"
            result["origination"]      = "brain_directional_discovery_failed"
            result["warnings"] = [
                f"FINAL-SHOT: Brain directional thesis ({_tdir}@"
                f"{bt.get('confidence')}, phase='{_phase}', family='none') — "
                f"phase unmapped and mechanical discovery found no playbook "
                f">= 45 (best: {_best} at {_best_score})"]
            return result

    # Hard block: no trade qualification (validator rejection)
    if snapshot.get("qualification", {}).get("status") == "no_trade":
        result = _NO_PLAYBOOK_RESULT.copy()
        result["warnings"] = ["Qualification status is no_trade — no playbook eligible"]
        return result

    best      = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score < 45:
        result = _NO_PLAYBOOK_RESULT.copy()
        result["warnings"] = [
            f"No playbook scored above minimum threshold (best: {best} at {best_score})"
        ]
        return result

    direction = _direction(snapshot)

    return {
        "selected_playbook":   best,
        "playbook_confidence": best_score,
        "direction":           direction,
        # AB-2A — inherits qualification's authoring source; never "structure"
        "direction_source":    snapshot.get("qualification", {}).get("direction_source", "inherited"),
        "origination":         "mechanical",   # FINAL-SHOT audit
        "eligible_tools":      eligible_tools(best, direction),
        "preferred_tools":     preferred_tools(best, direction),
        "status":              _status(best_score),
        "reasons":             _reasons(best, snapshot),
        "warnings":            _warnings(best, direction, snapshot),
    }
