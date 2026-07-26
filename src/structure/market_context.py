"""Market context — the authority layer. "What environment are we operating in?"

Stage 1 of the institutional narrative pipeline. Everything below it — PO3 state,
manipulation confluence, distribution, order block extraction — interprets local
events, and a local event has no directional meaning on its own. A bullish
structure break inside a larger bearish continuation is a retracement, not a
reversal. Without this layer the manipulation detector reports `bullish` on a
bearish continuation setup, which is exactly what it did on 2026-07-24 at 13:35.

Deliberately does NOT re-derive the environment. `classify_regime` already labels
trend / expansion / chop / range_rotation / reversal_attempt with trend, chop and
reversal scores; this consumes that. What it adds is what nothing upstream
provides:

  1. RETRACEMENT as an environment — a trending market whose current leg opposes
     the dominant bias. No existing label expresses it, and it is the environment
     the 2026-07-24 short was taken in.
  2. The DEALING RANGE and premium/discount position — "where is liquidity
     likely positioned", which no layer answers today.
  3. INTERPRETATION AUTHORITY — given HTF bias and a local event direction, is
     this continuation, retracement, liquidity engineering, or a genuine
     reversal? Downstream asks; it does not decide for itself.

Consumes processed evidence only — no raw candle math — matching po3_engine.
Every output carries a component breakdown; a context read without reasoning is
not auditable.
"""

HTF = "15m"          # the timeframe that owns directional authority
OPERATIVE = "5m"     # the timeframe setups are expressed on
LTF = "3m"           # local events

_BULL, _BEAR, _NEUTRAL = "bullish", "bearish", "neutral"

# Bias weights — starting values, NOT tuned.
W_HTF_STRUCTURE   = 35
W_ALIGNMENT       = 25
W_REGIME          = 25
W_OPERATIVE_STATE = 15

BIAS_AT = 35         # minimum net score to claim a direction

# compute_alignment reports agreement DEGREE, not direction — it confirms the
# HTF read in proportion to how many timeframes concur.
_ALIGNMENT_WEIGHT = {"full": 1.0, "partial": 0.5, "neutral": 0.0, "none": 0.0}
EQUILIBRIUM_BAND = 0.10   # +/- around 50% that counts as equilibrium

_TRENDING = {"trend_up", "trend_down"}
_EXPANDING = {"expansion_up", "expansion_down"}
_RANGING = {"chop", "range_rotation", "low_volatility"}
_REVERSING = {"reversal_attempt"}


def _dir_of(label):
    if label in ("trend_up", "expansion_up"):
        return _BULL
    if label in ("trend_down", "expansion_down"):
        return _BEAR
    return _NEUTRAL


def _bias_of(struct_tf):
    b = str((struct_tf or {}).get("bias", "")).lower()
    return b if b in (_BULL, _BEAR) else _NEUTRAL


def _score_htf_bias(structure, market_regime):
    """Directional authority by confluence. Returns (bias, score, components)."""
    votes = {_BULL: 0, _BEAR: 0}
    components = []

    def vote(name, direction, weight, detail):
        if direction in votes:
            votes[direction] += weight
        components.append({"name": name, "direction": direction,
                           "weight": weight, "detail": detail})

    htf_bias = _bias_of(structure.get(HTF))
    vote("htf_structure", htf_bias, W_HTF_STRUCTURE,
         f"{HTF} structure bias={htf_bias}, state={(structure.get(HTF) or {}).get('state')}")

    # compute_alignment returns a DEGREE of agreement (full/partial/neutral), not
    # a direction. It therefore confirms the HTF vote in proportion to how many
    # timeframes agree — it cannot originate a direction of its own.
    align = str(structure.get("alignment") or "").lower()
    align_mult = _ALIGNMENT_WEIGHT.get(align, 0.0)
    vote("structure_alignment", htf_bias if align_mult else _NEUTRAL,
         round(W_ALIGNMENT * align_mult),
         f"alignment={align or 'none'} (confirms {HTF} at {align_mult:.0%})")

    label = str((market_regime or {}).get("regime_label") or "")
    vote("regime_label", _dir_of(label), W_REGIME, f"regime={label or 'none'}")

    op_bias = _bias_of(structure.get(OPERATIVE))
    vote("operative_structure", op_bias, W_OPERATIVE_STATE,
         f"{OPERATIVE} structure bias={op_bias}")

    net = votes[_BULL] - votes[_BEAR]
    if abs(net) < BIAS_AT:
        bias = _NEUTRAL
    else:
        bias = _BULL if net > 0 else _BEAR
    return bias, votes, net, components


def _dealing_range(structure, liquidity, last_price, market_regime=None):
    """The operative range and where price sits inside it. Premium/discount is
    how ICT expresses 'where is liquidity likely positioned'.

    regime_features computes this first (it runs earlier in snapshot_builder) and
    owns it; consume that when present so the two layers cannot disagree about
    where the range is. The local derivation stays as a fallback for callers that
    have no regime block.
    """
    shared = (market_regime or {}).get("dealing_range")
    if isinstance(shared, dict) and shared.get("high") is not None:
        liq = liquidity.get(shared.get("source_tf")) or {}
        return {**shared,
                "buy_side_liquidity": liq.get("nearest_buy_side_liquidity"),
                "sell_side_liquidity": liq.get("nearest_sell_side_liquidity")}
    for tf in (HTF, OPERATIVE):
        st = structure.get(tf) or {}
        hi, lo = st.get("last_swing_high"), st.get("last_swing_low")
        if isinstance(hi, (int, float)) and isinstance(lo, (int, float)) and hi > lo:
            mid = (hi + lo) / 2
            pos = ((last_price - lo) / (hi - lo)) if isinstance(last_price, (int, float)) else None
            if pos is None:
                zone = "unknown"
            elif pos > 0.5 + EQUILIBRIUM_BAND:
                zone = "premium"
            elif pos < 0.5 - EQUILIBRIUM_BAND:
                zone = "discount"
            else:
                zone = "equilibrium"
            liq = liquidity.get(tf) or {}
            return {"source_tf": tf, "high": hi, "low": lo, "midpoint": round(mid, 2),
                    "position": round(pos, 3) if pos is not None else None,
                    "zone": zone,
                    "buy_side_liquidity": liq.get("nearest_buy_side_liquidity"),
                    "sell_side_liquidity": liq.get("nearest_sell_side_liquidity")}
    return {"source_tf": None, "high": None, "low": None, "midpoint": None,
            "position": None, "zone": "unknown",
            "buy_side_liquidity": None, "sell_side_liquidity": None}


def _environment(market_regime, htf_bias, local_bias, po3):
    """Environment, with RETRACEMENT derived — a trending market whose current
    leg opposes the dominant bias. No upstream label expresses that.

    The retracement judgement itself belongs to the hierarchy in regime_features,
    which owns the authority model and the invalidation level it rests on. This
    consumes that verdict when present rather than re-deriving it from a
    different timeframe, which would give two sources of truth that disagree.
    """
    label = str((market_regime or {}).get("regime_label") or "")
    relationship = str((market_regime or {}).get("htf_relationship") or "")
    if relationship:
        opposed = relationship == "retracement"
    else:
        opposed = (htf_bias in (_BULL, _BEAR) and local_bias in (_BULL, _BEAR)
                   and htf_bias != local_bias)

    if label in _REVERSING:
        return "reversal_conditions", f"regime={label}"
    if label in _TRENDING or label in _EXPANDING:
        if opposed:
            return "retracement", (f"regime={label} but local {OPERATIVE}/{LTF} bias "
                                   f"{local_bias} opposes htf {htf_bias}")
        return ("expansion" if label in _EXPANDING else "trending"), f"regime={label}"
    if label in _RANGING:
        return "ranging", f"regime={label}"
    return "undetermined", f"regime={label or 'none'}"


def interpret_local_event(context: dict, event_direction: str) -> dict:
    """THE authority downstream asks before assigning meaning to a local event.

    A local bullish break under bearish HTF authority is a retracement, not a
    reversal — unless the higher timeframe itself has shifted. Callers must not
    decide this for themselves; that is how downstream ends up compensating for
    missing upstream intelligence.
    """
    htf = context.get("htf_bias", _NEUTRAL)
    env = context.get("environment", "undetermined")
    zone = (context.get("dealing_range") or {}).get("zone", "unknown")

    if event_direction not in (_BULL, _BEAR):
        return {"reading": "undetermined", "reason": f"event direction {event_direction!r}"}
    if htf == _NEUTRAL:
        return {"reading": "undetermined",
                "reason": "no htf directional authority — event cannot be interpreted"}
    if event_direction == htf:
        return {"reading": "continuation",
                "reason": f"event {event_direction} agrees with htf {htf}"}
    if env == "reversal_conditions":
        return {"reading": "reversal_candidate",
                "reason": f"event opposes htf {htf} and environment is {env}"}
    counter_zone = (event_direction == _BULL and zone == "premium") or \
                   (event_direction == _BEAR and zone == "discount")
    if counter_zone:
        return {"reading": "liquidity_engineering",
                "reason": (f"event {event_direction} opposes htf {htf} and price is in "
                           f"{zone} — counter-trend move into the wrong side of the range")}
    return {"reading": "retracement",
            "reason": f"event {event_direction} opposes htf {htf}, environment {env}"}


def analyze_market_context(structure: dict, liquidity: dict, expansion: dict,
                           po3: dict, market_regime: dict,
                           last_price: float = None) -> dict:
    structure = structure or {}
    liquidity = liquidity or {}

    htf_bias, votes, net, bias_components = _score_htf_bias(structure, market_regime)
    # 5m is the PHASE timeframe in the hierarchy — 15m owns authority, 5m
    # describes the phase inside it, 1m/3m are execution. Reading the local leg
    # from 3m disagreed with regime_features, which uses 5m.
    local_bias = _bias_of(structure.get(OPERATIVE))
    if local_bias == _NEUTRAL:
        local_bias = _bias_of(structure.get(LTF))

    dealing_range = _dealing_range(structure, liquidity, last_price, market_regime)
    environment, env_detail = _environment(market_regime, htf_bias, local_bias, po3)

    if htf_bias in (_BULL, _BEAR) and local_bias in (_BULL, _BEAR):
        alignment = "aligned" if htf_bias == local_bias else "opposed"
    else:
        alignment = "neutral"

    ctx = {
        "environment": environment,
        "environment_detail": env_detail,
        "htf_bias": htf_bias,
        "htf_bias_net": net,
        "htf_bias_votes": votes,
        "local_bias": local_bias,
        "alignment": alignment,
        "dealing_range": dealing_range,
        "components": bias_components,
        "confidence": min(100, abs(net)),
    }
    # Self-describing: how the layer would read an event in each direction.
    ctx["event_readings"] = {
        _BULL: interpret_local_event(ctx, _BULL),
        _BEAR: interpret_local_event(ctx, _BEAR),
    }
    return ctx


def format_market_context(ctx: dict) -> str:
    """Audit trail, discretionary-legible."""
    dr = ctx.get("dealing_range") or {}
    lines = ["Market Context:", ""]
    for c in ctx.get("components", []):
        arrow = {"bullish": "+", "bearish": "-"}.get(c["direction"], " ")
        lines.append(f"  {c['name']:<20} {arrow}{c['weight']:<4} {c['direction']:<9} {c['detail']}")
    lines += ["",
              f"  HTF bias:       {ctx.get('htf_bias')} (net {ctx.get('htf_bias_net')})",
              f"  Local bias:     {ctx.get('local_bias')}  -> {ctx.get('alignment')}",
              f"  Environment:    {ctx.get('environment')}  ({ctx.get('environment_detail')})",
              f"  Dealing range:  {dr.get('low')} - {dr.get('high')} "
              f"(mid {dr.get('midpoint')}), price in {dr.get('zone')}"]
    if dr.get("buy_side_liquidity") or dr.get("sell_side_liquidity"):
        lines.append(f"  Liquidity:      buy-side {dr.get('buy_side_liquidity')}, "
                     f"sell-side {dr.get('sell_side_liquidity')}")
    lines.append("")
    for d, r in (ctx.get("event_readings") or {}).items():
        lines.append(f"  A {d} event reads as: {r['reading']}  ({r['reason']})")
    return "\n".join(lines)
