"""
Phase NA-1 — Narrative Authority Layer.

June 11 root cause: a context-blind structure engine owned the directional
narrative. It counted the 10:00 buy-side raid as a higher high (bullish),
while the AI ("bearish manipulation phase despite bullish bias"), the
delivery plane (bearish_delivery@25), and PO3 ("swept buy stops → bearish
intent") read the story correctly with no authority.

This layer synthesizes the market story from the WIDEST lens down:

  1. AI narrative      (external AI direction + confidence)
  2. Delivery          (PO3-derived delivery direction + confidence)
  3. Liquidity         (protected highs/lows, draw-on-liquidity)
  4. Structure         (DEMOTED: a witness, not the king)

ARBITRATION CONSTITUTION:
  - AI + Delivery agreement OWNS the direction. Structure cannot override
    it; opposing structure raises a conflict flag, nothing more.
  - AI vs Delivery disagreement = CONFLICTED. Structure may not break the
    tie (that is exactly the June 11 failure).
  - A single wide-lens voice vs opposing structure = CONFLICTED (downgrade,
    not silent structure win).
  - Structure alone (wide lenses silent) = witness mode: direction passes
    through at capped confidence, trades stay allowed (legacy behavior).
  - Trading INTO a protected level in the level's direction is forbidden:
    no longs into an unbroken protected high, no shorts into an unbroken
    protected low.

WHAT THIS LAYER IS NOT:
  - Not autonomous AI execution. The synthesis is deterministic code; the
    AI contributes evidence, not orders.
  - Not a bypass of anything: risk, max trades, daily loss, broker
    supremacy, stops, and the execution gate keep exactly their authority.
    This layer only decides what story the bot believes it is trading in,
    and the gate enforces story-coherence like any other check.

Authority: NARRATIVE_AUTHORITY=observe_only (default) | enforce.
Rollback: env flip. Never raises; degrades to witness mode on bad input.
"""
import os

from narrative_authority.liquidity_objectives import compute_liquidity_draw
from narrative_authority.protected_swings import _current_price

_DIRECTIONAL = ("bullish", "bearish")


def authority_level() -> str:
    level = os.getenv("NARRATIVE_AUTHORITY", "observe_only").lower().strip()
    return level if level in ("observe_only", "enforce") else "observe_only"


def _ai_min_conf() -> int:
    try:
        return int(os.getenv("NARRATIVE_AI_MIN_CONF", "55"))
    except (TypeError, ValueError):
        return 55


def _delivery_min_conf() -> int:
    try:
        return int(os.getenv("NARRATIVE_DELIVERY_MIN_CONF", "25"))
    except (TypeError, ValueError):
        return 25


def _protected_zone_pct() -> float:
    """Proximity band around a protected level that forbids trading into it."""
    try:
        return float(os.getenv("NARRATIVE_PROTECTED_ZONE_PCT", "0.3")) / 100.0
    except (TypeError, ValueError):
        return 0.003


def _opposite(direction: str) -> str:
    return "bearish" if direction == "bullish" else "bullish"


# ── Lens extraction ───────────────────────────────────────────────────────────

def _ai_lens(snapshot: dict) -> tuple:
    """AI-AUTH-1 — the AI lens is sourced from the ECU BRAIN, never the legacy
    wrapper. (Under PIPE-1 ordering narrative_authority is assembled BEFORE the
    Brain's canonical call, so this lens is empty on the live scan — exactly as
    it was when it read the wrapper, which also ran later. The re-source kills
    the LATENT wrapper wire: if assembly order ever changes, the enforce-mode
    narrative veto can only ever be Brain-fed.)"""
    ai  = snapshot.get("ai_brain", {}) or {}
    out = ai.get("output") if isinstance(ai.get("output"), dict) else {}
    d    = (out.get("narrative_direction") or "neutral").lower()
    conf = int(out.get("phase_confidence") or 0)
    if d in _DIRECTIONAL and conf >= _ai_min_conf():
        return d, conf
    return None, conf


def _delivery_lens(snapshot: dict) -> tuple:
    """
    Delivery direction from PO3 (distribution direction first, then
    manipulation direction — same cascade as the shared context), with the
    shared context's delivery_confidence. Falls back to a directional
    delivery_state string when PO3 is unavailable.
    """
    po3 = snapshot.get("po3", {}) or {}
    ctx = snapshot.get("shared_context", {}) or {}
    conf = int(ctx.get("delivery_confidence", 0) or 0)

    direction = None
    for key in ("distribution_direction", "manipulation_direction"):
        for tf in ("15m", "5m"):
            d = ((po3.get(tf) or {}).get(key) or "").lower()
            if d in _DIRECTIONAL:
                direction = d
                break
        if direction:
            break

    if direction is None:
        state = (ctx.get("delivery_state") or "").lower()
        for d in _DIRECTIONAL:
            if state.startswith(d):
                direction = d
                break

    if direction and conf >= _delivery_min_conf():
        return direction, conf
    return None, conf


def _structure_lens(snapshot: dict) -> str:
    bias = (snapshot.get("ai_context", {}) or {}).get("directional_bias", "neutral")
    return bias if bias in _DIRECTIONAL else None


# ── Phase classification ──────────────────────────────────────────────────────

def _classify_phase(snapshot: dict, direction: str, struct_dir: str) -> str:
    ctx       = snapshot.get("shared_context", {}) or {}
    po3       = snapshot.get("po3", {}) or {}
    po3_align = (po3.get("alignment") or "").lower()
    phases    = {tf: ((po3.get(tf) or {}).get("phase") or "").lower()
                 for tf in ("15m", "5m")}
    swept     = any(
        (snapshot.get("liquidity", {}).get(tf) or {}).get("sweep_detected")
        for tf in ("15m", "5m", "3m", "1m")
    )

    if ctx.get("exhaustion_present"):
        return "exhaustion"
    if "manipulation" in phases.values() or swept:
        return "manipulation"
    if po3_align == "manipulation_to_distribution" or "distribution" in phases.values():
        return "distribution"
    if direction in _DIRECTIONAL and struct_dir and direction != struct_dir:
        return "reversal"
    if ctx.get("continuation_intact"):
        return "continuation"
    if po3_align == "accumulation_building":
        return "accumulation"
    return "transition"


# ── Main synthesis ────────────────────────────────────────────────────────────

def build_narrative(snapshot: dict, swings: dict) -> dict:
    """
    Synthesize the market story. Returns the narrative authority block.
    Never raises — failure degrades to witness mode (no enforcement).
    """
    try:
        return _build(snapshot or {}, swings or {})
    except Exception as exc:  # noqa: BLE001
        return {
            "authority_level":     authority_level(),
            "narrative_direction": "neutral",
            "narrative_phase":     "transition",
            "narrative_confidence": 0,
            "protected_high":      None,
            "protected_low":       None,
            "active_liquidity_draw": None,
            "invalidation_level":  None,
            "trade_allowed":       True,
            "allowed_trade_direction":   "any",
            "forbidden_trade_direction": None,
            "reasons":  [],
            "warnings": [f"narrative engine error (witness fallback): {exc}"],
            "conflict_flags": [],
        }


def _build(snapshot: dict, swings: dict) -> dict:
    ai_dir, ai_conf       = _ai_lens(snapshot)
    del_dir, del_conf     = _delivery_lens(snapshot)
    struct_dir            = _structure_lens(snapshot)

    reasons, warnings, conflicts = [], [], []
    trade_allowed = True
    forbidden     = None

    # ── Arbitration: widest lens owns the story ───────────────────────────────
    if ai_dir and del_dir:
        if ai_dir == del_dir:
            direction  = ai_dir
            confidence = min(95, round((ai_conf + del_conf) / 2) + 15)
            reasons.append(
                f"AI ({ai_dir}@{ai_conf}) and Delivery ({del_dir}@{del_conf}) agree"
            )
            if struct_dir and struct_dir != direction:
                conflicts.append("structure_overruled")
                warnings.append(
                    f"structure bias {struct_dir} overruled by AI+Delivery {direction}"
                )
            forbidden = _opposite(direction)
        else:
            direction, confidence = "conflicted", 0
            trade_allowed = False
            conflicts.append("ai_delivery_disagreement")
            reasons.append(
                f"AI ({ai_dir}@{ai_conf}) vs Delivery ({del_dir}@{del_conf}) — "
                "structure may not break this tie"
            )
    elif ai_dir or del_dir:
        single, single_conf, lens = (
            (ai_dir, ai_conf, "AI") if ai_dir else (del_dir, del_conf, "Delivery")
        )
        if struct_dir == single:
            direction, confidence = single, min(90, single_conf + 10)
            reasons.append(f"{lens} ({single}@{single_conf}) confirmed by structure")
        elif struct_dir and struct_dir != single:
            direction, confidence = "conflicted", 0
            trade_allowed = False
            conflicts.append("wide_lens_vs_structure")
            reasons.append(
                f"{lens} reads {single}@{single_conf} against structure "
                f"{struct_dir} — conflicted, not silent structure win"
            )
        else:
            direction, confidence = single, single_conf
            reasons.append(f"{lens} ({single}@{single_conf}); structure neutral")
    else:
        # Witness mode: wide lenses silent — legacy structure behavior.
        direction  = struct_dir or "neutral"
        confidence = min(40, int(
            (snapshot.get("ai_context", {}) or {}).get("confidence_score", 0) or 0
        ))
        if struct_dir:
            warnings.append("structure-only narrative (wide lenses silent) — witness mode")

    # ── Protected levels: never trade into a defended swing ─────────────────
    ph    = swings.get("protected_high")
    pl    = swings.get("protected_low")
    price = _current_price(snapshot)

    if price is not None:
        zone = price * _protected_zone_pct()
        if ph and 0 <= ph["level"] - price <= zone:
            warnings.append(
                f"price {price:.2f} is inside the protected-high zone "
                f"({ph['level']:.2f}) — longs forbidden into spent buy-side"
            )
            if direction == "bullish":
                trade_allowed = False
                conflicts.append("long_into_protected_high")
            forbidden = "bullish" if forbidden != "bearish" else forbidden
        if pl and 0 <= price - pl["level"] <= zone:
            warnings.append(
                f"price {price:.2f} is inside the protected-low zone "
                f"({pl['level']:.2f}) — shorts forbidden into spent sell-side"
            )
            if direction == "bearish":
                trade_allowed = False
                conflicts.append("short_into_protected_low")
            forbidden = "bearish" if forbidden != "bullish" else forbidden

    phase = _classify_phase(snapshot, direction, struct_dir)
    if phase == "exhaustion" and direction in _DIRECTIONAL:
        warnings.append("narrative phase is exhaustion — late-entry risk")

    draw = compute_liquidity_draw(snapshot, swings, direction)

    invalidation = None
    if direction == "bearish" and ph:
        invalidation = ph["level"]
    elif direction == "bullish" and pl:
        invalidation = pl["level"]

    return {
        "authority_level":       authority_level(),
        "narrative_direction":   direction,
        "narrative_phase":       phase,
        "narrative_confidence":  confidence,
        "protected_high":        ph,
        "protected_low":         pl,
        "active_liquidity_draw": draw,
        "invalidation_level":    invalidation,
        "trade_allowed":         trade_allowed,
        "allowed_trade_direction": (
            direction if direction in _DIRECTIONAL and trade_allowed else "none"
        ),
        "forbidden_trade_direction": forbidden,
        "reasons":        reasons[:6],
        "warnings":       warnings[:6],
        "conflict_flags": conflicts[:6],
        # Witness record — full lens state for the audit trail
        "lenses": {
            "ai":        {"direction": ai_dir, "confidence": ai_conf},
            "delivery":  {"direction": del_dir, "confidence": del_conf},
            "structure": {"direction": struct_dir},
        },
    }


def narrative_permits(narrative: dict, proposed_direction: str) -> tuple:
    """
    Gate-side enforcement: (permits: bool, reason: str).
    Inert unless NARRATIVE_AUTHORITY=enforce. Fail-open on missing data.
    """
    try:
        if authority_level() != "enforce" or not narrative:
            return True, "narrative authority observe_only"
        pd = (proposed_direction or "").lower()
        if pd not in _DIRECTIONAL:
            return True, "no directional proposal"
        if not narrative.get("trade_allowed", True):
            return False, ("narrative forbids trading: "
                           + "; ".join(narrative.get("conflict_flags", [])
                                       or narrative.get("reasons", [])[:1]))
        if pd == narrative.get("forbidden_trade_direction"):
            return False, f"proposed {pd} trade is narrative-forbidden"
        return True, "narrative permits"
    except Exception as exc:  # noqa: BLE001
        return True, f"narrative check error (fail-open): {exc}"
