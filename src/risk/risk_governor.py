"""
Risk Governor — Phase 1I.
Reads the fully assembled snapshot and returns a risk verdict.
No execution, broker routing, stop loss, position sizing, or AI API calls.
"""

_HARD_BLOCK_NARRATIVES = {"conflicted", "exhaustion_risk", "compression"}
_SAFE_HARBOR_STATES    = {"stable", "expanding"}

_TIER_MULTIPLIERS = {
    "normal":  1.0,
    "reduced": 0.75,
    "minimal": 0.5,
    "blocked": 0.0,
}

_TIER_STATUS = {
    "normal":  "green",
    "reduced": "yellow",
    "minimal": "orange",
    "blocked": "red",
}

# Qualification status hierarchy — what each status allows at most.
# no_trade and watchlist are hard blocks (handled in _hard_blocks).
# candidate caps at minimal; qualified and elite impose no ceiling.
_QUAL_MAX_TIER = {
    "candidate": "minimal",
}

_TIER_RANK = {"normal": 0, "reduced": 1, "minimal": 2, "blocked": 3}
_RANK_TIER = ["normal", "reduced", "minimal", "blocked"]


# ── Hard Block Evaluator ──────────────────────────────────────────────────────

def _hard_blocks(snapshot: dict) -> list:
    """
    Returns a list of block reasons.
    Any non-empty result forces risk_tier to 'blocked' and trade_allowed to False.
    """
    blocks = []
    ai   = snapshot.get("ai_context",    {})
    vol  = snapshot.get("volatility",    {})
    qual = snapshot.get("qualification", {})

    if qual.get("status") == "no_trade":
        blocks.append("blocked: qualification is no_trade — no opportunity identified")

    if qual.get("status") == "watchlist":
        blocks.append("blocked: qualification is watchlist — environment has not cleared")

    if ai.get("confidence_tier") == "no_trade":
        blocks.append("confidence tier is no_trade — environment not tradeable")

    narrative = ai.get("market_narrative", "")
    if narrative in _HARD_BLOCK_NARRATIVES:
        blocks.append(f"market narrative '{narrative}' — engagement prohibited")

    if ai.get("market_state") == "dangerous":
        vol_5m = vol.get("5m", {}).get("state", "")
        vol_3m = vol.get("3m", {}).get("state", "")
        if vol_5m not in _SAFE_HARBOR_STATES or vol_3m not in _SAFE_HARBOR_STATES:
            blocks.append("dangerous market state — no lower-timeframe safe harbor")

    toxic = sum(
        1 for tf in ["15m", "5m"]
        if vol.get(tf, {}).get("state") in ("toxic", "explosive")
    )
    if toxic >= 2:
        blocks.append("15m and 5m both toxic/explosive — multi-timeframe volatility failure")

    return blocks


# ── Soft Restriction Evaluator ────────────────────────────────────────────────

def _soft_restrictions(snapshot: dict) -> tuple:
    """
    Returns (restriction_list, penalty_points).
    Restrictions reduce risk tier without blocking outright.
    """
    restrictions = []
    penalty      = 0

    ai     = snapshot.get("ai_context",    {})
    vol    = snapshot.get("volatility",    {})
    exp    = snapshot.get("expansion",     {})
    qual   = snapshot.get("qualification", {})
    pb     = snapshot.get("playbook",      {})
    po3    = snapshot.get("po3",           {})
    mem    = snapshot.get("memory",        {})
    struct = snapshot.get("structure",     {})

    # -- Qualification quality --
    # watchlist and no_trade are hard blocks — not evaluated here
    if qual.get("grade") in ("D", "F"):
        restrictions.append(f"qualification grade {qual.get('grade')} — weak opportunity")
        penalty += 1

    # -- Playbook quality --
    pb_name   = pb.get("selected_playbook", "no_playbook")
    pb_status = pb.get("status", "no_playbook")
    pb_conf   = pb.get("playbook_confidence", 0)

    if pb_name == "no_playbook":
        restrictions.append("no playbook selected — tactical game plan absent")
        penalty += 2
    elif pb_status == "forming":
        restrictions.append(f"playbook '{pb_name}' is forming — confirmation pending")
        penalty += 1
    elif pb_conf < 55:
        restrictions.append(f"playbook confidence {pb_conf} below threshold")
        penalty += 1

    # -- Volatility --
    vol_15m = vol.get("15m", {}).get("state", "")
    if vol_15m in ("toxic", "explosive"):
        restrictions.append(f"15m volatility classified {vol_15m} — elevated single-timeframe risk")
        penalty += 2
    elif vol_15m == "unstable":
        restrictions.append("15m volatility unstable — choppy conditions expected")
        penalty += 1

    if vol.get("15m", {}).get("range_acceleration", 1.0) > 1.5:
        restrictions.append("15m range accelerating rapidly — volatility expanding fast")
        penalty += 1

    # -- Expansion exhaustion --
    for tf in ["15m", "5m"]:
        ex = exp.get(tf, {})
        if ex.get("exhaustion_risk") == "high" or ex.get("state") == "exhaustion_risk":
            restrictions.append(f"{tf} expansion exhaustion risk is high")
            penalty += 1
            break
        if ex.get("exhaustion_risk") == "medium" and ex.get("state") == "mature_expansion":
            restrictions.append(f"{tf} mature expansion with medium exhaustion risk")
            penalty += 1
            break

    # -- Memory trend --
    if mem and mem.get("available"):
        g = mem.get("global") or {}
        if g.get("confidence_trend") == "falling":
            restrictions.append("confidence trend falling across snapshots — momentum declining")
            penalty += 1

        tfs_mem = mem.get("timeframes") or {}
        changed = [tf for tf in ["15m", "5m"] if tfs_mem.get(tf, {}).get("po3_phase_changed")]
        if len(changed) >= 2:
            restrictions.append(
                f"PO3 phase recently changed on {', '.join(changed)} — structure in flux"
            )
            penalty += 1

    # -- PO3 alignment --
    po3_align = po3.get("alignment", "")
    if po3_align in ("mixed", "no_clear_alignment"):
        restrictions.append(f"PO3 alignment is {po3_align} — delivery direction unclear")
        penalty += 1

    # -- Playbook direction --
    pb_dir = pb.get("direction", "neutral")
    if pb_dir in ("neutral", "conflicted"):
        restrictions.append(f"playbook direction is {pb_dir} — no confirmed directional edge")
        penalty += 1

    # -- Structure alignment --
    struct_align = struct.get("alignment", "neutral")
    if struct_align in ("neutral", "mixed"):
        restrictions.append(f"structure alignment is {struct_align} — MTF confluence absent")
        penalty += 1

    return restrictions, penalty


# ── Tier Resolution ───────────────────────────────────────────────────────────

def _risk_tier(blocks: list, penalty: int) -> str:
    if blocks:
        return "blocked"
    if penalty == 0:
        return "normal"
    if penalty <= 2:
        return "reduced"
    return "minimal"


# ── Authority Reason ──────────────────────────────────────────────────────────

def _authority_reason(
    tier: str, blocks: list, restrictions: list, snapshot: dict
) -> str:
    if tier == "blocked":
        qual_status = snapshot.get("qualification", {}).get("status", "")
        pb_status   = snapshot.get("playbook",      {}).get("status", "")
        if qual_status == "watchlist" and pb_status == "elite":
            return (
                "Tactical playbook is elite, but qualification is watchlist; "
                "environment has not cleared"
            )
        primary = blocks[0] if blocks else (restrictions[0] if restrictions else "accumulated risk conditions")
        return f"Blocked — {primary}"

    ai   = snapshot.get("ai_context",    {})
    qual = snapshot.get("qualification", {})
    pb   = snapshot.get("playbook",      {})

    if tier == "normal":
        qual_status = qual.get("status", "")
        pb_name     = pb.get("selected_playbook", "no_playbook")
        conf_tier   = ai.get("confidence_tier", "")
        if qual_status in ("elite", "qualified") and pb_name != "no_playbook":
            return (
                f"Green — {qual_status} qualification with "
                f"{pb_name.replace('_', ' ')} playbook active"
            )
        if conf_tier == "elite_setup":
            return "Green — elite setup conditions, no environmental restrictions"
        return "Green — all risk conditions within normal parameters"

    if tier == "reduced":
        primary = restrictions[0] if restrictions else "soft risk conditions present"
        return f"Reduced — {primary}"

    if tier == "minimal":
        primary = restrictions[0] if restrictions else "multiple risk conditions stacking"
        return f"Minimal — {primary}"

    return "Unknown risk tier"


# ── Governor Warnings ─────────────────────────────────────────────────────────

def _governor_warnings(snapshot: dict) -> list:
    """Passes through upstream layer warnings with deduplication."""
    ai   = snapshot.get("ai_context",    {})
    qual = snapshot.get("qualification", {})
    pb   = snapshot.get("playbook",      {})

    seen = set()
    w    = []

    # Elite playbook against weak qualification — surface before upstream warnings
    qual_status = qual.get("status", "")
    pb_status   = pb.get("status",   "")
    if qual_status == "watchlist" and pb_status == "elite":
        msg = "playbook elite but qualification weak — do not override risk block"
        seen.add(msg)
        w.append(msg)

    for warn in (
        list(ai.get("warnings",   []))
        + list(qual.get("warnings", []))
        + list(pb.get("warnings",  []))
    ):
        if warn and warn not in seen:
            seen.add(warn)
            w.append(warn)

    session = snapshot.get("session", "")
    if session in ("premarket", "overnight"):
        msg = f"{session} session — reduced liquidity environment"
        if msg not in seen:
            w.append(msg)

    return w


# ── Public Entry Point ────────────────────────────────────────────────────────

def evaluate_risk(snapshot: dict) -> dict:
    """
    Phase 1I — Risk Governor.
    Reads the fully assembled snapshot and returns a risk verdict.
    """
    blocks                = _hard_blocks(snapshot)
    restrictions, penalty = _soft_restrictions(snapshot)
    tier                  = _risk_tier(blocks, penalty)

    # Apply qualification-based tier ceiling when not already hard-blocked.
    # candidate → caps at minimal; qualified/elite → no ceiling imposed.
    if not blocks:
        qual_status = snapshot.get("qualification", {}).get("status", "")
        max_tier    = _QUAL_MAX_TIER.get(qual_status)
        if max_tier is not None:
            tier = _RANK_TIER[max(_TIER_RANK[tier], _TIER_RANK[max_tier])]

    multiplier       = _TIER_MULTIPLIERS[tier]
    governor_status  = _TIER_STATUS[tier]
    trade_allowed    = tier != "blocked"
    authority_reason = _authority_reason(tier, blocks, restrictions, snapshot)
    warnings         = _governor_warnings(snapshot)

    return {
        "trade_allowed":    trade_allowed,
        "governor_status":  governor_status,
        "risk_tier":        tier,
        "risk_multiplier":  multiplier,
        "authority_reason": authority_reason,
        "restrictions":     restrictions,
        "blocks":           blocks,
        "warnings":         warnings,
    }
