"""Order block extraction — the institutional footprint behind the repricing.

An order block is a variable-length accumulation/distribution region, not a
candle pattern. The candle count is an OUTPUT of detection, never an input: a
valid block may contain one candle or six, and the number carries no predictive
value on its own. `_find_ob` in price_levels returns a single candle body and
takes the most recent opposite-direction candle, which during a retracement
selects a candle inside the retracement itself — an "order block" price has
already traded through, with invalidation on the wrong side of entry.

This extractor asks the four questions instead:

  Where did the accumulation/distribution begin?
  Where did it end?
  What event confirmed repricing?
  What region supplied the inventory immediately preceding expansion?

BOUNDARIES, both objective:

  END   — the structure swing price rejected from. Authority names the side: a
          bearish auction rejects from a swing high, a bullish one from a low.
  START — walk back while the candle range stays compressed relative to ATR, and
          stop at the first candle that is not. Compression is the objective
          signature of inventory building rather than efficient trending.

Compression is EVIDENCE of accumulation, not its definition, so the region is
only designated an order block when the surrounding narrative confirms it —
manipulation and displacement confluence, under standing authority.

This layer must not compensate for missing upstream intelligence. Without
authority, or without displacement confirming that repricing actually occurred,
it declines to mark a block and reports which evidence was absent.
"""

# Range/ATR below which a candle counts as compressed. Starting value, NOT tuned.
COMPRESSION_AT = 0.80

# The block is bounded, never unbounded. A one-candle block is legitimate.
MIN_REGION = 1
MAX_REGION = 12

# Confluence required before a compressed region is called an order block.
MIN_DISPLACEMENT = 50      # repricing must actually have happened
MIN_MANIPULATION = 25      # liquidity engineering: contributing, not mandatory

_SWING_TOL = 0.25          # one MNQ tick

# Candles after the anchor that constitute the repricing leg — the window whose
# displacement confirms the block, evaluated once at formation.
LEG_WINDOW = 10


def _rng(c):
    r = c.get("range")
    return r if r is not None else (c["high"] - c["low"])


def _anchor_index(candles, struct, side):
    """Index of the swing the auction rejected from — the region's END."""
    key, level = ("high", (struct or {}).get("last_swing_high")) if side == "bearish" \
        else ("low", (struct or {}).get("last_swing_low"))
    if not isinstance(level, (int, float)):
        return None, None
    for i in range(len(candles) - 1, -1, -1):
        if abs(float(candles[i][key]) - float(level)) <= _SWING_TOL:
            return i, level
    return None, level


ATR_PERIOD = 14


def _local_atr(candles, anchor_idx, fallback=None):
    """ATR that prevailed WHERE THE REGION FORMED, not at the current bar.

    Compression is relative to volatility, and volatility moves. On 2026-07-24
    the 5m ATR was ~76 while the block formed at midday and ~40 by the 13:35
    entry; judging the earlier region with the later ATR made a genuinely
    compressed run look like expansion and the block vanished. Same principle as
    LEG-SCOPE — the measurement must describe the moment it is about.
    """
    if anchor_idx is None or anchor_idx <= 0:
        return fallback
    window = candles[max(0, anchor_idx - ATR_PERIOD):anchor_idx]
    if not window:
        return fallback
    return sum(_rng(c) for c in window) / len(window)


def _compressed_run(candles, anchor_idx, fallback_atr):
    """Walk back from the anchor while candles stay compressed. Count is output.

    ATR is evaluated PER CANDLE, over the period preceding it, not frozen at the
    anchor. Compression means "small relative to the volatility prevailing then",
    and volatility moves within a session: on 2026-07-24 a single anchor-frozen
    ATR of 66.71 cut the region at three candles because 11:50 missed the
    threshold by 0.85 points, while its own prevailing ATR comfortably contained
    it. Freezing one ATR across a multi-candle walk-back is the same error
    LEG-SCOPE fixed — a measurement that does not describe the moment it is about.
    """
    if anchor_idx is None:
        return []
    run = []
    for i in range(anchor_idx - 1, -1, -1):
        if len(run) >= MAX_REGION:
            break
        atr_i = _local_atr(candles, i, fallback=fallback_atr)
        if not atr_i or atr_i <= 0:
            break
        if _rng(candles[i]) >= COMPRESSION_AT * atr_i:
            break                      # compression broke — region starts after this
        run.append(i)
    return list(reversed(run))


LEG_HORIZON = 20


def _leg_end_index(candles, anchor_idx, struct, side):
    """Where the repricing leg bottomed (or topped) — found empirically.

    Matching a structure swing LEVEL fails here: the level comes from the 15m
    read and is searched for in 5m candles, so it frequently maps to no bar at
    all and the leg end silently fell back to a fixed offset that moved with
    series length. The leg's extreme within a bounded horizon is self-contained
    and stable as more bars arrive — it settles once the leg is over.
    """
    # Never terminate the leg on the final bar: live, it is still forming. On
    # 2026-07-24 the 13:10 candle read bearish while it held one minute of data
    # and bullish once closed, which flipped follow_through and un-confirmed a
    # block that had confirmed moments earlier. A leg must be judged on closed
    # candles only.
    end = min(anchor_idx + LEG_HORIZON, len(candles) - 2)
    if end <= anchor_idx:
        return min(anchor_idx + 1, len(candles) - 1)
    span = range(anchor_idx + 1, end + 1)
    key = "low" if side == "bearish" else "high"
    pick = min if side == "bearish" else max
    return pick(span, key=lambda i: candles[i][key])


def _leg_displacement(candles, anchor_idx, struct, side, atr, source_tf=None):
    """Score the repricing leg with the detector's own semantics, evaluated at
    the leg's COMPLETION rather than at the current bar.

    detect_displacement measures a trailing window — the right question for "is
    displacement happening now", the wrong one for "did displacement confirm this
    block". Passing the series truncated at the leg's end asks the second
    question without redefining the first.
    """
    from structure.displacement_detector import detect_displacement
    leg_end = _leg_end_index(candles, anchor_idx, struct, side)
    leg = candles[anchor_idx:leg_end + 1]
    eff = None
    if len(leg) >= 2:
        total = sum(_rng(c) for c in leg)
        if total > 0:
            eff = min(1.0, abs(leg[-1]["close"] - leg[0]["open"]) / total)
    # STEP 4B.8: cadence is PROVENANCE, threaded from the caller that selected
    # the series -- never inferred from timestamp spacing, which missing buckets
    # and scheduled breaks both make lie. Absent cadence means the canonical
    # imbalance proposition is refused, not scored on unvouched geometry.
    from toolbox.price_levels import TF_MINUTES
    return detect_displacement(candles[:leg_end + 1], struct, atr,
                               {"directional_efficiency": eff},
                               tf_minutes=TF_MINUTES.get(source_tf))


def extract_order_block(candles: list, atr: float, struct: dict = None,
                        authority: dict = None, manipulation: dict = None,
                        displacement: dict = None, source_tf: str = None) -> dict:
    """Locate the institutional footprint preceding repricing.

    Returns the region, its geometry, and the evidence — or a refusal naming the
    missing upstream evidence.
    """
    def refuse(reason, **extra):
        return {"present": False, "reason": reason, "zone": None,
                "region": None, "evidence": [], **extra}

    bias = (authority or {}).get("bias")
    if bias not in ("bullish", "bearish") or not (authority or {}).get("intact"):
        return refuse("no standing directional authority — the side an order block "
                      "would sit on is undetermined")
    if not candles or atr is None or atr <= 0:
        return refuse("no candles or no ATR — compression cannot be measured")

    # Authority names the side: a bearish auction distributes at a swing high.
    side = bias
    anchor_idx, level = _anchor_index(candles, struct, side)
    if anchor_idx is None:
        return refuse(f"the {side} structure swing does not map to these candles",
                      anchor_level=level)

    # Confirming evidence belongs to the moment the block FORMED, not to the
    # current bar. Displacement measured over the last N candles from now decays
    # as the repricing leg recedes, so a block validly established at 12:45
    # un-confirmed itself by 13:35 while price was retracing back into it —
    # exactly when it mattered. The repricing leg is the window immediately after
    # the anchor, and that is what must be scored.
    if displacement is None and len(candles) > anchor_idx + 1:
        displacement = _leg_displacement(candles, anchor_idx, struct, side, atr,
                                         source_tf)

    local_atr = _local_atr(candles, anchor_idx, fallback=atr)
    run = _compressed_run(candles, anchor_idx, local_atr)
    if len(run) < MIN_REGION:
        return refuse("no compressed region precedes the swing — inventory was not "
                      "built here", anchor_index=anchor_idx, local_atr=local_atr)

    region = [candles[i] for i in run]
    body_lo = round(min(min(c["open"], c["close"]) for c in region), 2)
    body_hi = round(max(max(c["open"], c["close"]) for c in region), 2)
    full_lo = round(min(c["low"] for c in region), 2)
    full_hi = round(max(c["high"] for c in region), 2)
    mean_threshold = round((body_lo + body_hi) / 2, 2)

    disp_score = int((displacement or {}).get("score") or 0)
    manip_score = int((manipulation or {}).get("score") or 0)

    evidence = [
        {"name": "compression", "present": True, "detail":
         f"{len(region)} candles below {COMPRESSION_AT}x local atr {local_atr:.2f} "
         f"before the swing"},
        {"name": "authority", "present": True, "detail":
         f"{bias} authority intact — block sits on the {side} side"},
        {"name": "displacement", "present": disp_score >= MIN_DISPLACEMENT,
         "detail": f"displacement score {disp_score} "
                   f"({'>=' if disp_score >= MIN_DISPLACEMENT else '<'} {MIN_DISPLACEMENT}) "
                   f"— repricing {'confirmed' if disp_score >= MIN_DISPLACEMENT else 'not confirmed'}"},
        {"name": "manipulation", "present": manip_score >= MIN_MANIPULATION,
         "detail": f"manipulation score {manip_score} "
                   f"({'>=' if manip_score >= MIN_MANIPULATION else '<'} {MIN_MANIPULATION})"},
    ]

    if disp_score < MIN_DISPLACEMENT:
        return refuse(
            "a compressed region exists but repricing was not confirmed — marking it "
            "would be this layer compensating for absent displacement evidence",
            region={"count": len(region), "start_index": run[0], "end_index": run[-1]},
            evidence=evidence)

    return {
        "present": True,
        "side": side,
        "reason": (f"{len(region)}-candle {side} order block: compression before the "
                   f"{side} swing at {level}, repricing confirmed at displacement "
                   f"{disp_score}"),
        "zone": {
            "body_low": body_lo, "body_high": body_hi,
            "full_low": full_lo, "full_high": full_hi,
            # The level that matters: only the mean threshold produces a stop that
            # fits the risk cap — the block extreme is as wide as the swing.
            "mean_threshold": mean_threshold,
            "block_extreme": full_hi if side == "bearish" else full_lo,
        },
        "region": {"count": len(region), "start_index": run[0], "end_index": run[-1],
                   "anchor_index": anchor_idx, "anchor_level": level},
        "evidence": evidence,
        "scores": {"displacement": disp_score, "manipulation": manip_score},
    }


def format_order_block(ob: dict) -> str:
    if not ob:
        return "Order Block: none"
    lines = ["Order Block:", ""]
    for e in (ob.get("evidence") or []):
        mark = "yes" if e["present"] else "no "
        lines.append(f"  [{mark}] {e['name']:<14} {e['detail']}")
    lines.append("")
    if not ob.get("present"):
        lines.append(f"  NOT MARKED: {ob.get('reason')}")
        if ob.get("region"):
            lines.append(f"  (a {ob['region']['count']}-candle compressed region was found)")
        return "\n".join(lines)
    z, r = ob["zone"], ob["region"]
    lines += [f"  side            : {ob['side']}",
              f"  candles         : {r['count']}   (an output, not an input)",
              f"  body zone       : {z['body_low']} - {z['body_high']}",
              f"  full range      : {z['full_low']} - {z['full_high']}",
              f"  mean threshold  : {z['mean_threshold']}",
              f"  block extreme   : {z['block_extreme']}",
              "",
              f"  {ob['reason']}"]
    return "\n".join(lines)


# ── Lifecycle ─────────────────────────────────────────────────────────────────
#
# A block does not stop existing because the repricing that created it has
# receded. It persists until price comes back and either respects it or breaks
# it. That life is fully determined by the candles since formation, so it is
# derived rather than carried in cross-scan state — deterministic, replayable,
# and immune to a missed scan.
#
# States, in precedence order:
#   invalidated            price CLOSED beyond the block extreme — the block failed
#   fully_mitigated        price traded through the far side of the body
#   mean_threshold_tagged  price reached the 50% — the level that matters
#   touched                price entered the body but no more
#   unmitigated            price has not returned

MITIGATION_STATES = ("unmitigated", "touched", "mean_threshold_tagged",
                     "fully_mitigated", "invalidated")


def track_mitigation(candles: list, block: dict) -> dict:
    """How the block has been treated since it formed."""
    if not block or not block.get("present"):
        return {"state": None, "reason": "no block to track"}

    region, zone = block["region"], block["zone"]
    side = block["side"]
    body_lo, body_hi = zone["body_low"], zone["body_high"]
    mean = zone["mean_threshold"]
    extreme = zone["block_extreme"]
    span = max(body_hi - body_lo, 1e-9)

    # Mitigation is a RETURN, so it cannot begin until price has left. Counting
    # from the anchor scored the departure itself as mitigation: at the 12:45
    # cutoff on 2026-07-24 that read seven touches and 90% penetration while
    # price was still on its way out of the block.
    departed = None
    for i in range(region["anchor_index"] + 1, len(candles)):
        outside = (candles[i]["high"] < body_lo) if side == "bearish" \
            else (candles[i]["low"] > body_hi)
        if outside:
            departed = i
            break
    if departed is None:
        return {"state": "unmitigated", "bars_since": len(candles) - region["anchor_index"] - 1,
                "touches": 0, "max_penetration": 0.0, "first_touch_index": None,
                "departed_index": None, "tradeable": False,
                "detail": "price has not yet left the block — no return to measure"}

    start = departed + 1
    after = candles[start:]
    if not after:
        return {"state": "unmitigated", "bars_since": 0, "touches": 0,
                "max_penetration": 0.0, "first_touch_index": None,
                "departed_index": departed, "tradeable": False,
                "detail": "price left the block; no candles since"}

    touches, first_touch, deepest = 0, None, 0.0
    entered = tagged = full = invalid = False

    for offset, c in enumerate(after):
        if side == "bearish":
            reach = c["high"]                 # price rises back into the block
            inside = reach >= body_lo
            pen = (reach - body_lo) / span
            if c["close"] > extreme:
                invalid = True
            if reach >= mean:
                tagged = True
            if reach >= body_hi:
                full = True
        else:
            reach = c["low"]                  # price falls back into the block
            inside = reach <= body_hi
            pen = (body_hi - reach) / span
            if c["close"] < extreme:
                invalid = True
            if reach <= mean:
                tagged = True
            if reach <= body_lo:
                full = True
        if inside:
            entered = True
            touches += 1
            if first_touch is None:
                first_touch = start + offset
        deepest = max(deepest, min(1.0, max(0.0, pen)))

    state = ("invalidated" if invalid else
             "fully_mitigated" if full else
             "mean_threshold_tagged" if tagged else
             "touched" if entered else "unmitigated")

    detail = {
        "unmitigated": "price has not returned to the block",
        "touched": (f"price entered the body but stalled at "
                    f"{deepest:.0%} — mean threshold {mean} not reached"),
        "mean_threshold_tagged": f"price reached the mean threshold {mean}",
        "fully_mitigated": "price traded through the full body",
        "invalidated": f"price closed beyond the block extreme {extreme}",
    }[state]

    return {"state": state, "bars_since": len(after), "touches": touches,
            "max_penetration": round(deepest, 3), "first_touch_index": first_touch,
            "departed_index": departed,
            "tradeable": state in ("touched", "mean_threshold_tagged"),
            "detail": detail}


def format_mitigation(m: dict) -> str:
    if not m or not m.get("state"):
        return "Mitigation: none"
    return "\n".join([
        "Mitigation:", "",
        f"  state           : {m['state']}",
        f"  bars since      : {m.get('bars_since')}",
        f"  touches         : {m.get('touches')}",
        f"  max penetration : {m.get('max_penetration')}",
        f"  tradeable       : {m.get('tradeable')}",
        "",
        f"  {m.get('detail')}",
    ])
