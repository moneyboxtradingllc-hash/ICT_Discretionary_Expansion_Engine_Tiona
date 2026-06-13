"""
Phase AB-2A — Structure-Authorship Firewall.

MAP-0 proved the generation lane was structure-rooted: structure_engine._bias
→ ai_context.directional_bias → qualification.direction → playbook.direction →
toolbox → trade candidate. June 11 is the cost: a buy-side raid read as a
"higher high" authored a bullish long.

This module is the single source of truth for "what may author a trade
direction." STRUCTURE MAY NOT. Structure remains a witness (swings, BOS/MSS,
lag/conflict warnings) but never the originating vote.

Authoring sources, in priority (all NON-structure):
  1. delivery_protected — PO3 distribution_direction, then manipulation_direction
  2. liquidity_draw     — sweep+reclaim semantics (below_low→bullish, above_high→bearish)
  (narrative_authority / ai_brain are added as authoring sources in AB-4+, NOT here)

Firewall verdict:
  - non-structure source present, structure agrees or silent → that direction
  - non-structure source present, structure DISAGREES → "conflicted"
    (safety; promoting delivery OVER a dissenting structure witness is AB-5)
  - no non-structure source, structure has a bias → "conflicted"
    (structure_witness_only — NEVER bullish/bearish)
  - nothing directional → "neutral" (fallback_none)

AB-2A is a FIREWALL ONLY. It removes structure from the author's chair; it does
NOT wire AI Brain, narrative, delivery-as-outright-author, or two-sided
generation (those are AB-4/AB-5). Default ON. Rollback:
STRUCTURE_AUTHORSHIP_FIREWALL=false restores the exact pre-AB-2A path.

Never raises.
"""
import os

_TFS = ("15m", "5m", "3m", "1m")
_DIRECTIONAL = ("bullish", "bearish")

# Valid direction_source tags (Requirement 2)
SOURCE_DELIVERY        = "delivery_protected"
SOURCE_LIQUIDITY       = "liquidity_draw"
SOURCE_NARRATIVE       = "narrative_authority"   # reserved for AB-4
SOURCE_AI_BRAIN        = "ai_brain"              # reserved for AB-4
SOURCE_STRUCTURE_ONLY  = "structure_witness_only"
SOURCE_CONFLICT        = "delivery_vs_structure_conflict"
SOURCE_FALLBACK_NONE   = "fallback_none"
SOURCE_LEGACY          = "legacy_structure_rooted"   # firewall OFF


def firewall_enabled() -> bool:
    return os.getenv("STRUCTURE_AUTHORSHIP_FIREWALL", "true").lower().strip() == "true"


def _sweep_semantic_direction(liquidity: dict) -> "str | None":
    for tf in _TFS:
        liq = (liquidity or {}).get(tf, {}) or {}
        if liq.get("sweep_detected") and liq.get("reclaim_detected"):
            sd = liq.get("sweep_direction", "")
            if sd == "below_low":
                return "bullish"
            if sd == "above_high":
                return "bearish"
    return None


def nonstructure_direction(po3: dict, liquidity: dict) -> tuple:
    """Direction from non-structure authoring evidence only. (dir|None, source|None)."""
    po3 = po3 or {}
    for tf in ("15m", "5m"):
        d = (po3.get(tf, {}) or {}).get("distribution_direction")
        if d in _DIRECTIONAL:
            return d, SOURCE_DELIVERY
    sweep = _sweep_semantic_direction(liquidity or {})
    if sweep in _DIRECTIONAL:
        return sweep, SOURCE_LIQUIDITY
    for tf in ("15m", "5m"):
        m = (po3.get(tf, {}) or {}).get("manipulation_direction")
        if m in _DIRECTIONAL:
            return m, SOURCE_DELIVERY
    return None, None


def authored_direction(structure_bias: str, po3: dict, liquidity: dict) -> tuple:
    """
    The firewall decision. structure_bias is WITNESS input (from ai_context /
    structure); it can confirm or conflict but never originate.
    Returns (direction, direction_source). Never raises.
    """
    try:
        sb = structure_bias if structure_bias in _DIRECTIONAL else None
        nd, source = nonstructure_direction(po3, liquidity)

        if nd is None:
            # No non-structure author. Structure may NOT fill the vacuum.
            if sb is not None:
                return "conflicted", SOURCE_STRUCTURE_ONLY
            return "neutral", SOURCE_FALLBACK_NONE

        if sb is not None and sb != nd:
            # Structure dissents from the authoring source → conservative block.
            return "conflicted", SOURCE_CONFLICT

        # Authoring source originates; structure agrees or is silent.
        return nd, source
    except Exception:  # noqa: BLE001
        return "neutral", SOURCE_FALLBACK_NONE
