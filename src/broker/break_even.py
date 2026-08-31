"""POSITION-MANAGEMENT-BREAK-EVEN-1 — retire risk once the trade has paid for it.

2026-08-24, live PRAC. Luna authored a thesis, mechanics verified it, risk sized
it, execution submitted it, the venue filled it -- 8 MNQ short at 29090.25 with
an 18.00-point stop. The organism then had no opinion about the position at all.
The operator watched it go green and closed it by hand. Every layer worked
except the one that owns a trade AFTER it exists.

WHAT THIS IS
    at +1.00R, move protection to cost-adjusted break-even, once.

WHAT THIS IS NOT
    not a trailing stop, not partials, not a target change, not a re-entry, and
    emphatically not a second opinion about the thesis. No provider is called;
    a trade that is already open is not a discretionary question, and asking a
    model whether to protect a winner is how a rule becomes a negotiation.

R IS MEASURED FROM WHAT HAPPENED, NOT FROM WHAT WAS REQUESTED. The requested
entry on 2026-08-24 was 29092.25 and the fill was 29090.25: a 2.00-point
improvement that makes requested-R and actual-R different numbers (18.00 vs
20.00 points to the same stop). Managing from the request would move protection
at the wrong moment in one direction and pay for slippage twice in the other.

BREAK-EVEN IS NOT THE FILL. Closing at the fill price loses the round trip. The
adjustment uses the SAME canonical cost model risk sizing already uses
(`topstepx_combine_risk`), so "flat" means flat after fees, commissions and the
declared slippage reserve -- never a number invented here.

THE MONOTONIC LAW IS NOT REIMPLEMENTED. `protection_state.evaluate_advance` is
the single verifier of whether protection may move; this module decides only
WHETHER TO PROPOSE and WHAT to propose. A second copy of "may risk be restored"
is exactly the duplicated-authority defect this repository keeps finding.

Pure. No broker, no network, no provider, no clock. Never raises.
"""
from __future__ import annotations

SCHEMA = "break_even.v1"

#: The trade has returned its own risk once. Frozen by operator doctrine; this
#: is a management rule, not a tunable knob, and a configurable trigger would
#: invite fitting it to whichever session hurt most recently.
TRIGGER_R = 1.00

# ── outcomes ─────────────────────────────────────────────────────────────────
PROPOSE = "propose_break_even"   # move protection; caller must still verify
HOLD = "hold"                    # lawful, nothing to do yet
REFUSED = "refused"              # cannot be evaluated truthfully

# ── reasons ──────────────────────────────────────────────────────────────────
NOT_YET = "below_trigger"
ALREADY_APPLIED = "break_even_already_applied"
NO_FILL = "no_actual_fill_price"
NO_STOP = "no_initial_stop_price"
NO_QUOTE = "no_fresh_executable_quote"
DEGENERATE_R = "initial_risk_is_not_positive"
UNKNOWN_DIRECTION = "unknown_direction"
NOT_ARMED = "protection_baseline_not_armed"
WOULD_RESTORE_RISK = "break_even_would_restore_risk"

_LONG, _SHORT = "long", "short"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _side(direction):
    d = str(direction or "").strip().lower()
    if d in ("long", "buy", "bullish"):
        return _LONG
    if d in ("short", "sell", "bearish"):
        return _SHORT
    return None


def initial_risk_points(*, direction, entry_fill_price, initial_stop_price):
    """1R, in points, from the ACTUAL fill. None when it cannot be measured.

    Signed by direction so a stop on the wrong side yields a non-positive
    number and is refused upstream rather than silently producing a mirrored
    trigger.
    """
    side, fill, stop = _side(direction), _num(entry_fill_price), _num(initial_stop_price)
    if side is None or fill is None or stop is None:
        return None
    return (fill - stop) if side == _LONG else (stop - fill)


def open_r_multiple(*, direction, entry_fill_price, initial_stop_price,
                    current_price):
    """How many R the position is currently ahead. None when unmeasurable."""
    r = initial_risk_points(direction=direction, entry_fill_price=entry_fill_price,
                            initial_stop_price=initial_stop_price)
    side, fill, now = _side(direction), _num(entry_fill_price), _num(current_price)
    if r is None or r <= 0 or now is None or fill is None:
        return None
    moved = (now - fill) if side == _LONG else (fill - now)
    return moved / r


def normalize_to_tick(*, direction, raw_price, tick_size):
    """Snap a protective stop to a price the venue will actually accept.

    A CORRECT NUMBER IS NOT AN EXECUTABLE ONE. The 2026-08-24 specimen produced
    a raw cost-adjusted break-even of 29088.64 against an MNQ tick of 0.25 --
    arithmetically right and impossible to submit. Leaving that for the broker
    adapter to "clean up" would put price geometry in the layer least able to
    know which direction is safe.

    ALWAYS TOWARD MORE PROTECTION, NEVER LESS:

        LONG    ceil  -- the stop sits ABOVE the fill, so rounding UP keeps at
                         least the full friction allowance
        SHORT   floor -- the stop sits BELOW the fill, so rounding DOWN does

    On that specimen the two neighbouring ticks are 29088.75 and 29088.50.
    Rounding to the nearer one (29088.75) protects 1.50 points against a 1.61
    point allowance -- it UNDER-COVERS the round trip, which is the one outcome
    break-even exists to prevent. 29088.50 protects 1.75 and is correct.

    Tick geometry comes from the contract, never from a hard-coded instrument.
    """
    side, raw, tick = _side(direction), _num(raw_price), _num(tick_size)
    if side is None or raw is None or not tick or tick <= 0:
        return None
    import math
    # Decimal-noise guard: a raw value mathematically ON a tick can land a hair
    # below it in binary, and ceil() would then push a whole tick too far.
    n = raw / tick
    if abs(n - round(n)) < 1e-9:
        n = round(n)
        return round(n * tick, 10)
    steps = math.ceil(n) if side == _LONG else math.floor(n)
    return round(steps * tick, 10)


def cost_adjusted_break_even(*, direction, entry_fill_price, contract=None,
                             quantity=1, friction_points=None, tick_size=None):
    """The venue-valid price at which closing leaves the account whole.

    Beyond the fill by the round-trip friction, so it is ALWAYS at least
    marginally profitable rather than exactly flat, and then snapped to a tick
    in the conservative direction. `friction_points` may be supplied directly
    (already per-contract, in points); otherwise the canonical risk model is
    asked, and if it cannot answer, this returns None rather than guessing.

    When no tick geometry is available the RAW price is returned unrounded --
    the caller then knows it is holding an un-normalized number rather than a
    silently mis-rounded one.
    """
    side, fill = _side(direction), _num(entry_fill_price)
    if side is None or fill is None:
        return None
    pts = _num(friction_points)
    if pts is None:
        pts = _friction_points_from_canonical_model(contract, quantity)
    if pts is None:
        return None
    raw = (fill + pts) if side == _LONG else (fill - pts)
    tick = _num(tick_size)
    if tick is None:
        tick = _num(getattr(contract, "tick_size", None))
    snapped = normalize_to_tick(direction=direction, raw_price=raw, tick_size=tick)
    return round(raw, 4) if snapped is None else snapped


def _friction_points_from_canonical_model(contract, quantity):
    """Round-trip friction per contract, expressed in POINTS.

    Delegates to `topstepx_combine_risk` -- the same measured fees/commissions
    and declared slippage reserve that sizing already uses. Never invents a
    cost: an unavailable model returns None and the caller refuses.
    """
    try:
        if contract is None:
            return None
        from broker.topstepx_combine_risk import friction_per_contract
        # `total` = measured fixed round trip + the DECLARED slippage reserve.
        # Both halves are taken exactly as sizing takes them; splitting them
        # here would let management and sizing disagree about what a trade costs.
        dollars = _num((friction_per_contract(contract) or {}).get("total"))
        if dollars is None:
            return None
        # Points per dollar comes from the contract's own tick geometry, so a
        # different instrument converts correctly without a second table.
        tick_size = _num(getattr(contract, "tick_size", None))
        tick_value = _num(getattr(contract, "tick_value", None))
        if not tick_size or not tick_value or tick_value <= 0:
            return None
        return (dollars / tick_value) * tick_size
    except Exception:  # noqa: BLE001 — management must never raise
        return None


def evaluate(*, direction, entry_fill_price, initial_stop_price,
             active_protective_stop, current_price, armed: bool,
             already_applied: bool = False, contract=None, quantity=1,
             friction_points=None, tick_size=None) -> dict:
    """Should protection move to break-even right now?

    Returns PROPOSE / HOLD / REFUSED and, when proposing, the exact price. The
    caller MUST still put that price through `protection_state.evaluate_advance`
    -- this function never asserts the move is lawful, only that it is wanted.

    IDEMPOTENT BY CONSTRUCTION. `already_applied` short-circuits, and even
    without it a second evaluation proposes the identical price, which the
    monotonic verifier answers NO_OP. Repeated +1R observations therefore cannot
    produce a second venue amendment.
    """
    def out(outcome, reason=None, detail="", **extra):
        return dict({"schema": SCHEMA, "outcome": outcome, "reason": reason,
                     "detail": detail, "trigger_r": TRIGGER_R,
                     "direction": _side(direction)}, **extra)

    side = _side(direction)
    if side is None:
        return out(REFUSED, UNKNOWN_DIRECTION, f"direction {direction!r}")
    # ARMED MEANS VENUE-PROVEN. Managing against a provisional bracket would
    # advance a stop the venue may not actually be holding.
    if not armed:
        return out(REFUSED, NOT_ARMED,
                   "structural protection is not venue-proven; a provisional "
                   "bracket is not a management baseline")
    if already_applied:
        return out(HOLD, ALREADY_APPLIED, "break-even has already been applied")
    fill = _num(entry_fill_price)
    if fill is None:
        return out(REFUSED, NO_FILL,
                   "R is measured from the ACTUAL fill; requested entry is not a fill")
    if _num(initial_stop_price) is None:
        return out(REFUSED, NO_STOP, "no initial stop to measure R against")
    risk = initial_risk_points(direction=direction, entry_fill_price=fill,
                               initial_stop_price=initial_stop_price)
    if risk is None or risk <= 0:
        return out(REFUSED, DEGENERATE_R,
                   f"initial risk {risk} is not positive; stop is on the wrong "
                   f"side of the fill or equal to it")
    # NO QUOTE, NO MANAGEMENT. A settled close is not where this would execute,
    # and substituting one is the exact defect EXEC-PRICE-FRESHNESS-1 removed.
    now = _num(current_price)
    if now is None:
        return out(REFUSED, NO_QUOTE,
                   "management requires a fresh governed executable quote",
                   initial_risk_points=risk)
    r_now = open_r_multiple(direction=direction, entry_fill_price=fill,
                            initial_stop_price=initial_stop_price,
                            current_price=now)
    common = {"initial_risk_points": round(risk, 4),
              "open_r": None if r_now is None else round(r_now, 4)}
    if r_now is None or r_now < TRIGGER_R:
        return out(HOLD, NOT_YET,
                   f"open {common['open_r']}R is short of {TRIGGER_R}R", **common)
    # THE NORMALIZED, VENUE-VALID PRICE is what everything downstream sees --
    # the monotonic verifier and the actuator must both reason about the price
    # that will actually be submitted, never a raw decimal that cannot be.
    be = cost_adjusted_break_even(direction=direction, entry_fill_price=fill,
                                  contract=contract, quantity=quantity,
                                  friction_points=friction_points,
                                  tick_size=tick_size)
    if be is None:
        return out(REFUSED, "cost_model_unavailable",
                   "round-trip friction could not be obtained from the canonical "
                   "model; break-even is not guessed", **common)
    # A LAST HONEST CHECK, NOT A SECOND MONOTONIC AUTHORITY. If break-even sits
    # farther from price than protection already is, proposing it would ask the
    # verifier to restore risk. Refusing here keeps the trace readable; the
    # verifier remains the one that decides.
    active = _num(active_protective_stop)
    if active is not None:
        worse = (be < active) if side == _LONG else (be > active)
        if worse:
            return out(HOLD, WOULD_RESTORE_RISK,
                       f"protection at {active} is already better than "
                       f"break-even {be}", break_even_price=be, **common)
    return out(PROPOSE, None,
               f"open {common['open_r']}R >= {TRIGGER_R}R; protect at {be}",
               break_even_price=be, **common)
