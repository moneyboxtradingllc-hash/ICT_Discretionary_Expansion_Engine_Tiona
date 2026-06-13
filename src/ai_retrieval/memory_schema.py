"""
Phase AB-3 — Memory record schema + provenance hygiene.

A memory record captures a market situation (and, for trades, its outcome) so
the AI Brain can later ask "what have I seen that resembles this?". Provenance
is first-class: structure-derived direction is stored for audit but never
retrieved as an authoritative analog.

Observe-only. Never raises.
"""

# Provenance — valid non-structure authoring sources (AB-2A/2B/2C lineage).
VALID_SOURCES = frozenset({
    "sweep_semantics", "liquidity_reclaim", "protected_swing",
    "explicit_po3_transition", "delivery_protected", "liquidity_draw",
    "ai_brain", "narrative_authority",
})
# Explicitly structure-tainted sources.
INVALID_SOURCES = frozenset({
    "structure", "structure_bias", "bias_only", "directional_bias", "bos", "mss",
})


def classify_provenance(direction_source: "str | None") -> tuple:
    """(source_validated, structure_tainted). Never raises."""
    src = (direction_source or "").lower().strip()
    validated = src in VALID_SOURCES
    tainted   = src in INVALID_SOURCES
    return validated, tainted


def is_authoritative(record: dict) -> bool:
    """A record is an authoritative analog only when its source is validated
    and not structure-tainted. Unknown provenance is non-authoritative."""
    prov = record.get("provenance", {}) or {}
    return bool(prov.get("source_validated")) and not prov.get("structure_tainted", False)


def make_record(
    *,
    timestamp, symbol, session=None, regime=None, volatility_state=None,
    narrative_direction=None, narrative_phase=None, active_liquidity_draw=None,
    protected_high=None, protected_low=None,
    delivery_direction=None, delivery_direction_source=None,
    active_playbook=None, toolbox_state=None, entry_model=None,
    direction_source=None,
    trade_taken=False, trade_direction=None, win_loss_be=None,
    r_multiple=None, management_path=None,
    record_type="market",   # "market" | "trade"
) -> dict:
    """Build a canonical memory record with provenance. Never raises."""
    validated, tainted = classify_provenance(direction_source)
    return {
        "record_type": record_type,
        "market_context": {
            "timestamp": timestamp, "symbol": symbol, "session": session,
            "regime": regime, "volatility_state": volatility_state,
        },
        "narrative_context": {
            "narrative_direction": narrative_direction,
            "narrative_phase": narrative_phase,
            "active_liquidity_draw": active_liquidity_draw,
            "protected_high": protected_high,
            "protected_low": protected_low,
            "delivery_direction": delivery_direction,
            "delivery_direction_source": delivery_direction_source,
        },
        "playbook_context": {
            "active_playbook": active_playbook,
            "toolbox_state": toolbox_state,
            "entry_model": entry_model,
        },
        "outcome_context": {
            "trade_taken": trade_taken,
            "trade_direction": trade_direction,
            "win_loss_be": win_loss_be,
            "r_multiple": r_multiple,
            "management_path": management_path,
        },
        "provenance": {
            "direction_source": direction_source,
            "source_validated": validated,
            "structure_tainted": tainted,
        },
    }


def win_loss_be_from_r(realized_r) -> "str | None":
    try:
        r = float(realized_r)
    except (TypeError, ValueError):
        return None
    if r > 0.05:
        return "win"
    if r < -0.05:
        return "loss"
    return "be"
