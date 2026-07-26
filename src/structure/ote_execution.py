"""OTE / execution — turn a mitigated order block into a checked trade plan.

Last layer of the pipeline. Everything above establishes WHAT the market is
doing; this asks whether that produces a trade, and refuses when it does not.

OTE IS ANCHORED TO THE ORDER BLOCK, not to a bare swing. A swing-to-swing OTE
pocket ignores where inventory was actually built: on 2026-07-24 the 0.62-0.79
pocket sat at 28555-28590 while price turned at 28544, so the engine waited in a
zone price never reached. The block supplies the reference the auction respected.

THE ENTRY ZONE is bounded by two levels that must agree:

  swing 50%          equilibrium of the leg the block delivered
  block mean threshold   50% of the block body — consequent encroachment

On 2026-07-24 those were 28529.13 and 28551.75, and price turned at 28544.25 —
inside the zone, between them. Requiring both is what keeps the entry tied to the
institutional footprint rather than to a fibonacci level in isolation.

INVALIDATION is a doctrine choice and is therefore a parameter, not an assumption
buried in the code. The block is ~105 points tall, so its extreme yields a stop
of the same order as the swing high — 75+ points, far outside a 25pt cap. Only
the mean threshold produces a stop the risk engine can accept. That is the
default; `invalidation` selects the other explicitly.
"""

TICK = 0.25
STOP_BUFFER_TICKS = 2

INVALIDATION_MEAN_THRESHOLD = "mean_threshold"
INVALIDATION_BLOCK_EXTREME = "block_extreme"

# A block is only tradeable once price has come back to it and not broken it.
TRADEABLE_STATES = ("touched", "mean_threshold_tagged")

MIN_REWARD_TO_RISK = 2.0


def _round_tick(p):
    return round(round(p / TICK) * TICK, 2)


def build_execution_plan(block: dict, mitigation: dict, leg_extreme: float,
                         max_stop_points: float = 25.0,
                         invalidation: str = INVALIDATION_MEAN_THRESHOLD,
                         min_rr: float = MIN_REWARD_TO_RISK) -> dict:
    """Produce a checked trade plan, or a refusal naming what failed.

    `leg_extreme` is the far side of the leg the block delivered — the swing the
    repricing reached — used for both the swing 50% and the target.
    """
    checks = []

    def check(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})
        return bool(ok)

    def refuse(reason):
        return {"tradeable": False, "reason": reason, "checks": checks,
                "entry": None, "stop": None, "target": None}

    if not block or not block.get("present"):
        check("block_present", False, (block or {}).get("reason", "no order block"))
        return refuse("no confirmed order block — nothing to execute against")
    check("block_present", True, f"{block['region']['count']}-candle {block['side']} block")

    state = (mitigation or {}).get("state")
    if not check("block_mitigated", state in TRADEABLE_STATES,
                 f"mitigation state {state!r} "
                 f"({'tradeable' if state in TRADEABLE_STATES else 'not tradeable'})"):
        return refuse(f"block is {state} — price has not returned to it, or it is spent")

    side = block["side"]
    z = block["zone"]
    anchor = block["region"]["anchor_level"]
    if not isinstance(leg_extreme, (int, float)):
        check("leg_extreme_known", False, "no leg extreme")
        return refuse("the leg the block delivered has no measurable extreme")
    check("leg_extreme_known", True, f"leg extreme {leg_extreme}")

    swing_50 = _round_tick((anchor + leg_extreme) / 2)
    mean_threshold = z["mean_threshold"]

    # Entry zone: between the leg's equilibrium and the block's consequent
    # encroachment. Order depends on side; both must be on the correct side of
    # the leg for the setup to be coherent.
    lo, hi = (min(swing_50, mean_threshold), max(swing_50, mean_threshold))
    if not check("entry_zone_coherent", hi > lo,
                 f"entry zone {lo} - {hi} (swing 50% {swing_50}, "
                 f"mean threshold {mean_threshold})"):
        return refuse("swing equilibrium and block mean threshold coincide — no zone")

    entry = _round_tick((lo + hi) / 2)

    ref = mean_threshold if invalidation == INVALIDATION_MEAN_THRESHOLD \
        else z["block_extreme"]

    # A short leg pushes the swing 50% ABOVE the mean threshold on a bearish
    # setup, which puts the whole entry zone beyond the invalidation reference.
    # The stop-side check below would catch it, but only as a confusing "wrong
    # side" message; naming the cause is what makes the refusal useful.
    zone_ok = (hi <= ref) if side == "bearish" else (lo >= ref)
    if not check("entry_zone_inside_invalidation", zone_ok,
                 f"entry zone {lo}-{hi} vs {invalidation} {ref} — "
                 f"{'inside' if zone_ok else 'beyond'}"):
        return refuse(f"the leg is too short: its 50% ({swing_50}) sits beyond the "
                      f"{invalidation} ({ref}), so the entry zone has no room "
                      f"under invalidation")
    buffer = STOP_BUFFER_TICKS * TICK
    stop = _round_tick(ref + buffer) if side == "bearish" else _round_tick(ref - buffer)

    stop_distance = round(abs(stop - entry), 2)
    if not check("stop_correct_side",
                 (stop > entry) if side == "bearish" else (stop < entry),
                 f"stop {stop} vs entry {entry} for a {side} setup"):
        return refuse("invalidation sits on the wrong side of entry")

    if not check(f"stop_within_{max_stop_points:g}pts", stop_distance <= max_stop_points,
                 f"stop distance {stop_distance} vs cap {max_stop_points} "
                 f"(invalidation={invalidation})"):
        return refuse(f"stop {stop_distance}pts exceeds the {max_stop_points}pt cap "
                      f"using {invalidation}")

    target = _round_tick(leg_extreme)
    reward = round(abs(entry - target), 2)
    rr = round(reward / stop_distance, 2) if stop_distance > 0 else 0.0

    if not check("target_correct_side",
                 (target < entry) if side == "bearish" else (target > entry),
                 f"target {target} vs entry {entry}"):
        return refuse("target sits on the wrong side of entry")

    if not check(f"reward_to_risk_{min_rr:g}", rr >= min_rr,
                 f"reward {reward} / risk {stop_distance} = {rr}R "
                 f"({'>=' if rr >= min_rr else '<'} {min_rr}R)"):
        return refuse(f"{rr}R does not clear the {min_rr}R minimum")

    return {
        "tradeable": True,
        "side": side,
        "entry": entry,
        "entry_zone": {"low": lo, "high": hi,
                       "swing_50": swing_50, "mean_threshold": mean_threshold},
        "stop": stop,
        "stop_distance": stop_distance,
        "invalidation_reference": invalidation,
        "target": target,
        "reward": reward,
        "reward_to_risk": rr,
        "checks": checks,
        "reason": (f"{side} entry {entry} in the block zone {lo}-{hi}, stop {stop} "
                   f"({stop_distance}pts off {invalidation}), target {target} = {rr}R"),
    }


def format_execution_plan(p: dict) -> str:
    lines = ["Execution Plan:", ""]
    for c in (p.get("checks") or []):
        lines.append(f"  [{'pass' if c['pass'] else 'FAIL'}] {c['name']:<26} {c['detail']}")
    lines.append("")
    if not p.get("tradeable"):
        lines.append(f"  NO TRADE: {p.get('reason')}")
        return "\n".join(lines)
    z = p["entry_zone"]
    lines += [f"  side            : {p['side']}",
              f"  entry zone      : {z['low']} - {z['high']}",
              f"    swing 50%     : {z['swing_50']}",
              f"    mean threshold: {z['mean_threshold']}",
              f"  entry           : {p['entry']}",
              f"  stop            : {p['stop']}   ({p['stop_distance']}pts, "
              f"{p['invalidation_reference']})",
              f"  target          : {p['target']}   ({p['reward']}pts)",
              f"  reward:risk     : {p['reward_to_risk']}R"]
    return "\n".join(lines)
