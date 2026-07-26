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


def extract_order_block(candles: list, atr: float, struct: dict = None,
                        authority: dict = None, manipulation: dict = None,
                        displacement: dict = None) -> dict:
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
