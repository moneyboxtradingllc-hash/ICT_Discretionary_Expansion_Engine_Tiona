"""OBJECTIVE-SCALE-PRESERVATION-1A — the liquidity hierarchy, scale intact.

REPRESENTATION ONLY. Nothing imports this yet. It changes no candidate, no
objective, no target, no payload and no model input, and it is deliberately
NOT wired into `brain_input` or `luna_candidate_producer` -- both are Brain
closure members, and exposing these facts to Luna is Step 1B's decision to make
under its own authorization, not a side effect of publishing them.

WHAT DISAPPEARS TODAY. `snapshot.liquidity` already holds pools per timeframe.
`brain_input` then collapses them:

    _TFS = ("15m", "5m", "3m", "1m")
    "nearest_buy_side": next((liq[tf]["nearest_buy_side_liquidity"]
                              for tf in _TFS if ...), None)

`next()` over an HTF-first tuple returns THE HIGHEST TIMEFRAME THAT HAS A POOL
-- not the nearest one. On 2026-08-25 the snapshot held

    1m 29249.25 · 3m 29345.00 · 5m 29345.00 · 15m 29409.25

and Luna received only 29409.25, labelled `nearest_buy_side`, while her own path
ownership had propagated no further than 1m. The 1m pool roughly 23 points away
was never published as an objective at all. The name is not merely imprecise; it
describes the opposite of what the code does. Renaming it needs a consumer
audit and is queued, NOT done here.

ONE LEVEL, MANY WITNESSES. Two timeframes may reference the same executable
price -- 3m and 5m both sat at 29345.00 that day. They are ONE destination seen
at two scales, never two independent objectives, or a level would gain weight
merely for being observed twice. Merged levels keep every supporting timeframe
so the scale evidence survives the merge.

THIS MODULE ASSERTS NOTHING ABOUT ENTITLEMENT. It does not rank, prefer, or
declare any pool primary; it does not know whether a pool is still untaken (see
the queued LIQUIDITY-POOL-LIFECYCLE work, which the 2026-08-25 opening raid
showed is a separate and real gap). It reports where liquidity is and at what
scale. What a given ownership depth is entitled to reach is Step 1B's question.
"""
from __future__ import annotations

SCHEMA = "liquidity_scale.v1"

BUY_SIDE = "buy_side"
SELL_SIDE = "sell_side"

#: Shallowest to deepest. Used only to ORDER provenance, never to rank
#: destinations -- a deeper witness does not make a level a better target.
TF_ORDER = ("1m", "3m", "5m", "15m")
TF_RANK = {tf: i + 1 for i, tf in enumerate(TF_ORDER)}

_FIELD = {BUY_SIDE: "nearest_buy_side_liquidity",
          SELL_SIDE: "nearest_sell_side_liquidity"}

#: How two prices are judged to be ONE level when no contract tick is supplied.
#: `snapshot.liquidity` carries no tick geometry (verified 2026-08-25), so the
#: caller may pass one; absent that this rounds to four places rather than
#: inventing a tolerance. Reported in the result as `price_identity` so a reader
#: never has to guess which rule was applied.
DECIMAL_IDENTITY = "round_4dp"
TICK_IDENTITY = "half_tick"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def same_level(a, b, tick_size=None) -> bool:
    """Do two prices denote ONE executable destination?

    Mirrors the rule `break_even_actuator.same_level` applies to protective
    stops. Deliberately re-stated rather than imported: that module is broker
    execution and this is market structure, and coupling them so one could
    silently change the other's semantics is the kind of shared-authority seam
    this codebase has already paid for once.
    """
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return False
    tick = _num(tick_size)
    if tick and tick > 0:
        return abs(a - b) <= tick / 2.0
    return round(a, 4) == round(b, 4)


def _signed_distance(price, reference, side):
    """Distance TOWARD the pool. Positive means ahead of price in that
    direction; negative means price has already traded past it."""
    if price is None or reference is None:
        return None
    return round((price - reference) if side == BUY_SIDE
                 else (reference - price), 4)


def canonical_pools(liquidity_by_tf: dict, *, side: str, reference_price=None,
                    tick_size=None) -> list:
    """Every distinct pool on one side, with its supporting timeframes.

    Ordered shallowest-witness first, then by price, so the output reads as a
    hierarchy rather than an arbitrary set. A timeframe with no pool is simply
    absent -- never a null placeholder that a later reader could mistake for a
    level at zero.
    """
    field = _FIELD.get(side)
    if not field or not isinstance(liquidity_by_tf, dict):
        return []
    merged = []
    for tf in TF_ORDER:
        block = liquidity_by_tf.get(tf)
        if not isinstance(block, dict):
            continue
        price = _num(block.get(field))
        if price is None:
            continue
        for row in merged:
            if same_level(row["price"], price, tick_size):
                if tf not in row["supporting_timeframes"]:
                    row["supporting_timeframes"].append(tf)
                break
        else:
            merged.append({"price": price, "side": side,
                           "supporting_timeframes": [tf]})
    for row in merged:
        row["supporting_timeframes"].sort(key=lambda t: TF_RANK.get(t, 99))
        row["shallowest_timeframe"] = row["supporting_timeframes"][0]
        row["deepest_timeframe"] = row["supporting_timeframes"][-1]
        row["distance"] = _signed_distance(row["price"], reference_price, side)
    merged.sort(key=lambda r: (TF_RANK.get(r["shallowest_timeframe"], 99),
                               r["price"]))
    return merged


def hierarchy(liquidity_by_tf: dict, *, reference_price=None,
              tick_size=None) -> dict:
    """Both sides, scale preserved, same-price levels merged.

    Purely derived: it reads `snapshot.liquidity` and computes nothing new. No
    swing detector, no liquidity detector, no entitlement claim.
    """
    ref = _num(reference_price)
    return {
        "schema": SCHEMA,
        "reference_price": ref,
        "price_identity": TICK_IDENTITY if _num(tick_size) else DECIMAL_IDENTITY,
        "tick_size": _num(tick_size),
        BUY_SIDE: canonical_pools(liquidity_by_tf, side=BUY_SIDE,
                                  reference_price=ref, tick_size=tick_size),
        SELL_SIDE: canonical_pools(liquidity_by_tf, side=SELL_SIDE,
                                   reference_price=ref, tick_size=tick_size),
    }


def legacy_flattened(liquidity_by_tf: dict, side: str):
    """What `brain_input` publishes today, reproduced for COMPARISON ONLY.

    Exists so a test can prove the legacy value is unchanged and so corpus
    characterisation can measure how often "nearest" differs from the actually
    nearest pool. Never call this to make a decision.
    """
    field = _FIELD.get(side)
    if not field or not isinstance(liquidity_by_tf, dict):
        return None
    for tf in ("15m", "5m", "3m", "1m"):            # the production order
        block = liquidity_by_tf.get(tf)
        if isinstance(block, dict):
            value = block.get(field)
            if value is not None:
                return value
    return None
