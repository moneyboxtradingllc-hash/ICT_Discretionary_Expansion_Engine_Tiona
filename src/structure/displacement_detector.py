"""Displacement confluence — did institutions actually commit?

"When institutions commit, price should not simply drift away. It should expand
with conviction. If price merely teeters around after leaving consolidation, that
is weak evidence. If price rapidly accelerates away with large directional
candles and leaves inefficiencies behind, that is strong evidence."

The existing signal cannot express that. `displacement_detected` is a bare bool —
true when ANY candle in the last five has a body over an ATR-derived threshold.
It carries no magnitude, no direction, and no imbalance evidence, so a 1.4x
nudge and a 2.1x drive that tears three gaps in the tape are the same value.

Observed on 2026-07-24: the candles immediately after the order block ran 1.4x
and 0.6x average body, while the real expansion (2.1x, 1.6x) and every FVG landed
from 12:25 onward. A bool cannot separate those; a score with components can.

Six sources, scored by confluence and reported per-component:

  displacement_magnitude   largest body in the window, in ATR
  imbalance_created        FVGs left behind by the leg
  structure_break          BOS / MSS
  directional_efficiency   net travel vs total travel (leg-scoped upstream)
  follow_through           consecutive candles in one direction
  no_hesitation            share of the window opposing the move

Weights are starting values, NOT tuned. Telemetry lands before tuning.
"""
from toolbox.price_levels import find_fvgs

# Component weights — unvalidated starting values.
W_MAGNITUDE   = 30
W_IMBALANCE   = 25
W_STRUCTURE   = 15
W_EFFICIENCY  = 15
W_FOLLOW      = 10
W_NO_HESITATE = 5

CONFIRMED_AT = 50
POSSIBLE_AT  = 25

# A displacement candle must clear this multiple of ATR to count as conviction.
MAGNITUDE_ATR_MULT = 1.5
EFFICIENCY_AT      = 0.30
FOLLOW_THROUGH_AT  = 3
HESITATION_MAX     = 0.40

LOOKBACK = 10
_MIN_CANDLES = 5


def _body(c):
    b = c.get("body_size")
    return b if b is not None else abs(c["close"] - c["open"])


def _dir_of(c):
    d = c.get("direction")
    if d in ("bullish", "bearish"):
        return d
    return "bullish" if c["close"] > c["open"] else ("bearish" if c["close"] < c["open"]
                                                    else "neutral")


def _magnitude(window, atr):
    if not atr or atr <= 0:
        return False, "no atr", None, 0.0
    best, best_c = 0.0, None
    for c in window:
        m = _body(c) / atr
        if m > best:
            best, best_c = m, c
    if best_c is None:
        return False, "no candles", None, 0.0
    ok = best >= MAGNITUDE_ATR_MULT
    detail = (f"largest body {_body(best_c):.2f} = {best:.2f}x atr {atr:.2f} "
              f"({'>=' if ok else '<'} {MAGNITUDE_ATR_MULT}x)")
    return ok, detail, (_dir_of(best_c) if ok else None), round(best, 2)


def _imbalance(window, direction):
    if direction not in ("bullish", "bearish"):
        return False, "no leg direction to scan for imbalance", None, 0
    gaps = find_fvgs(window, direction)
    if not gaps:
        return False, f"no {direction} imbalance left behind", None, 0
    total = sum(g["size"] for g in gaps)
    return True, (f"{len(gaps)} {direction} FVG(s), {total:.2f} pts total, "
                  f"largest {max(g['size'] for g in gaps):.2f}"), direction, len(gaps)


def _structure_break(struct):
    bos = bool((struct or {}).get("bos"))
    mss = bool((struct or {}).get("mss"))
    if bos or mss:
        parts = [n for n, v in (("BOS", bos), ("MSS", mss)) if v]
        return True, " + ".join(parts) + " on this timeframe", None
    return False, "no BOS or MSS", None


def _efficiency(exp):
    eff = (exp or {}).get("directional_efficiency")
    if not isinstance(eff, (int, float)):
        return False, "directional_efficiency unavailable", None
    ok = eff >= EFFICIENCY_AT
    return ok, (f"directional_efficiency {eff:.3f} "
                f"({'>=' if ok else '<'} {EFFICIENCY_AT})"), None


def _follow_through(window):
    if not window:
        return False, "no window", None
    last = _dir_of(window[-1])
    if last == "neutral":
        return False, "final candle has no direction", None
    n = 1
    for c in reversed(window[:-1]):
        if _dir_of(c) == last:
            n += 1
        else:
            break
    ok = n >= FOLLOW_THROUGH_AT
    return ok, (f"{n} consecutive {last} candles "
                f"({'>=' if ok else '<'} {FOLLOW_THROUGH_AT})"), (last if ok else None)


def _no_hesitation(window, direction):
    if direction not in ("bullish", "bearish") or not window:
        return False, "no leg direction", None
    opposing = sum(1 for c in window if _dir_of(c) not in (direction, "neutral"))
    share = opposing / len(window)
    ok = share <= HESITATION_MAX
    return ok, (f"{opposing}/{len(window)} candles oppose the {direction} leg "
                f"({share:.0%} {'<=' if ok else '>'} {HESITATION_MAX:.0%})"), None


def detect_displacement(candles: list, struct: dict = None, atr: float = None,
                        expansion: dict = None, authority: dict = None) -> dict:
    """Score institutional commitment by confluence over a lookback window."""
    components, votes = [], []

    def add(name, present, weight, detail, direction=None):
        components.append({"name": name, "present": bool(present),
                           "points": weight if present else 0,
                           "weight": weight, "detail": detail})
        if present and direction:
            votes.append(direction)

    if not candles or len(candles) < _MIN_CANDLES:
        return {"score": 0, "classification": "none", "direction": None,
                "magnitude_atr": 0.0, "imbalance_count": 0, "components": [],
                "lookback": 0,
                "reason": f"insufficient candles ({len(candles) if candles else 0})"}

    window = candles[-LOOKBACK:]

    present, detail, d, magnitude = _magnitude(window, atr)
    add("displacement_magnitude", present, W_MAGNITUDE, detail, d)

    # Leg direction: the displacement candle names it; otherwise the net move.
    leg = d or ("bullish" if window[-1]["close"] > window[0]["open"] else
                "bearish" if window[-1]["close"] < window[0]["open"] else None)

    present, detail, d, gaps = _imbalance(window, leg)
    add("imbalance_created", present, W_IMBALANCE, detail, d)

    present, detail, d = _structure_break(struct)
    add("structure_break", present, W_STRUCTURE, detail, d)

    present, detail, d = _efficiency(expansion)
    add("directional_efficiency", present, W_EFFICIENCY, detail, d)

    present, detail, d = _follow_through(window)
    add("follow_through", present, W_FOLLOW, detail, d)

    present, detail, d = _no_hesitation(window, leg)
    add("no_hesitation", present, W_NO_HESITATE, detail, d)

    raw = sum(c["points"] for c in components)
    score = min(100, raw)
    classification = ("displacement_confirmed" if score >= CONFIRMED_AT else
                      "displacement_possible" if score >= POSSIBLE_AT else "none")
    direction = max(set(votes), key=votes.count) if votes else leg

    out = {"score": score, "raw_score": raw, "classification": classification,
           "direction": direction, "magnitude_atr": magnitude,
           "imbalance_count": gaps, "components": components,
           "lookback": len(window)}

    # Coherence with standing authority — reported, never used to rewrite the
    # score. Displacement against authority is real displacement; it is the
    # authority that is then in question, and that call is not made here.
    if authority and authority.get("bias") in ("bullish", "bearish"):
        if direction in ("bullish", "bearish"):
            agrees = direction == authority["bias"]
            out["authority_coherence"] = {
                "coherent": agrees,
                "note": (f"{direction} displacement "
                         f"{'delivers' if agrees else 'opposes'} "
                         f"{authority['bias']} authority")}
        else:
            out["authority_coherence"] = {"coherent": None,
                                          "note": "displacement has no direction"}
    return out


def format_displacement(d: dict) -> str:
    lines = ["Displacement Score:", ""]
    for c in d.get("components", []):
        lines.append(f"  {c['name']:<24} {('+' + str(c['points'])) if c['points'] else '0':>5}"
                     f"   {c['detail']}")
    lines += ["", f"  Total: {d.get('score', 0)}/100",
              f"  Classification: {d.get('classification', 'none')}"]
    if d.get("direction"):
        lines.append(f"  Direction: {d['direction']}")
    if d.get("authority_coherence"):
        lines.append(f"  Authority: {d['authority_coherence']['note']}")
    return "\n".join(lines)
