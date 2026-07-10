"""
REPLAY-3 — SimBroker: candle-walk outcome simulation (2026-07-09).

Scores a trade (real, replayed, or counterfactual) against the archived 1m tape.
Mirrors the live doctrine: market-order fill at the NEXT 1m open after the
authorization timestamp (FC-0B), stop from invalidation/zone, breakeven at
BE_TRIGGER_R, take-profit at TP_R, EOD flatten. Ambiguous candles resolve
PESSIMISTICALLY (adverse extreme before favorable — a long's low is tested
before its high), so simulated expectancy is a floor, never flattery.

Pure function of (tape, trade spec) — no broker imports, no orders, no state.
This is the outcome engine that feeds the adaptive loop's shadow-expectancy
tables and the replay engine's win/loss/expectancy metrics.
"""
from datetime import datetime, timezone, time as dtime
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_EOD_FLATTEN_ET = dtime(15, 55)


def _ts(v) -> "datetime | None":
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def simulate_trade(candles: list, signal_time, direction: str, stop: float,
                   entry_price: float = None, target_r: float = 2.0,
                   breakeven_r: float = 1.0, eod_flatten: bool = True,
                   max_bars: int = None) -> "dict | None":
    """Walk one trade forward on 1m candles.

    candles     : archived 1m bars (oldest-first, dicts with timestamp/o/h/l/c)
    signal_time : authorization timestamp
    entry_price : None  -> MARKET fill at the next bar's open (FC-0B doctrine)
                  price -> LIMIT semantics: the trade does NOT exist until a
                  bar actually TRADES at that price (lo <= entry <= hi). The
                  0708 calibration proved instant-fill-at-a-quoted-price is
                  fantasy (a short limit above the market filled 'instantly'
                  scored a win the hand-verified tape scored a loss).
    direction   : bullish|long / bearish|short
    stop        : absolute stop price (invalidation level / zone edge)
    target_r    : take-profit in R (None = no target, ride to stop/EOD)
    breakeven_r : move stop to entry once this favorable R is touched
                  (None = never)
    Returns {entry_time, entry, initial_stop, exit_time, exit, exit_reason,
             r, mfe_r, mae_r, bars_held} or None (never filled / invalid spec).
    """
    t0 = _ts(signal_time)
    if t0 is None or stop is None:
        return None
    is_long = str(direction).lower() in ("bullish", "long", "buy")

    fwd = []
    for c in candles:
        ct = _ts(c.get("timestamp"))
        if ct is None or ct <= t0:
            continue
        fwd.append((ct, c))
    if max_bars:
        fwd = fwd[:max_bars]
    if not fwd:
        return None

    if entry_price is None:
        entry = float(fwd[0][1]["open"])            # market: next bar's open
    else:
        entry = float(entry_price)                  # limit: wait for a cross
        # Side-aware fill: a buy limit fills when price trades AT/UNDER it, a
        # sell limit when price trades AT/OVER it — including gaps through the
        # level (the resting order fills at limit-or-better; we book the limit
        # itself, the pessimistic side). Strict bar-touch missed a gap-through
        # fill on the 0708 calibration tape.
        fill_i = None
        for i, (_ct, c) in enumerate(fwd):
            crossed = (float(c["low"]) <= entry) if is_long \
                else (float(c["high"]) >= entry)
            if crossed:
                fill_i = i
                break
        if fill_i is None:
            return None                             # never filled — no trade
        fwd = fwd[fill_i:]                          # outcome walk from fill bar
    stop = float(stop)
    risk = (entry - stop) if is_long else (stop - entry)
    if risk <= 0:
        return None   # stop on the wrong side — invalid spec, not a trade

    target = None
    if target_r is not None:
        target = entry + risk * target_r if is_long else entry - risk * target_r

    cur_stop = stop
    be_armed = breakeven_r is not None
    be_level = (entry + risk * breakeven_r if is_long
                else entry - risk * breakeven_r) if be_armed else None

    mfe = mae = 0.0
    exit_price = exit_reason = exit_time = None
    bars = 0

    for ct, c in fwd:
        bars += 1
        hi, lo = float(c["high"]), float(c["low"])
        fav = (hi - entry) if is_long else (entry - lo)
        adv = (entry - lo) if is_long else (hi - entry)
        mfe = max(mfe, fav)
        mae = max(mae, adv)

        # PESSIMISM: adverse extreme first — stop before target within a bar.
        stop_hit = (lo <= cur_stop) if is_long else (hi >= cur_stop)
        if stop_hit:
            exit_price, exit_time = cur_stop, ct
            exit_reason = "breakeven_stop" if cur_stop == entry else "stop"
            break
        if target is not None and ((hi >= target) if is_long else (lo <= target)):
            exit_price, exit_time, exit_reason = target, ct, "target"
            break
        # BE arms AFTER survival of the bar (favorable touch, no stop-out)
        if be_armed and ((hi >= be_level) if is_long else (lo <= be_level)):
            cur_stop, be_armed = entry, False
        # EOD flatten at the close of the 15:55 ET bar
        if eod_flatten and ct.astimezone(_ET).time() >= _EOD_FLATTEN_ET:
            exit_price, exit_time, exit_reason = float(c["close"]), ct, "eod_flatten"
            break

    if exit_reason is None:   # tape ended with position open — mark at last close
        exit_time, last = fwd[-1]
        exit_price, exit_reason = float(last["close"]), "tape_end"

    r = ((exit_price - entry) if is_long else (entry - exit_price)) / risk
    return {
        "direction": "long" if is_long else "short",
        "entry_time": fwd[0][0].isoformat() if entry_price is None else t0.isoformat(),
        "entry": round(entry, 4), "initial_stop": round(stop, 4),
        "risk_points": round(risk, 4),
        "exit_time": exit_time.isoformat(), "exit": round(exit_price, 4),
        "exit_reason": exit_reason,
        "r": round(r, 3),
        "mfe_r": round(mfe / risk, 3), "mae_r": round(mae / risk, 3),
        "bars_held": bars,
    }


def stop_from_intent(entry_zone: dict, direction: str,
                     invalidation_level: float = None,
                     buffer: float = 0.0) -> "float | None":
    """Live doctrine: stop = invalidation_level; fallback zone edge ± buffer
    (order_builder's derivation, mirrored)."""
    if invalidation_level is not None:
        return float(invalidation_level)
    z = entry_zone or {}
    is_long = str(direction).lower() in ("bullish", "long", "buy")
    edge = z.get("zone_low") if is_long else z.get("zone_high")
    if edge is None:
        return None
    return float(edge) - buffer if is_long else float(edge) + buffer
