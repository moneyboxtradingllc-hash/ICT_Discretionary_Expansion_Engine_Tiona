"""BREAK-EVEN-2A — what 1R meant, recoverable after the process dies.

`break_even.evaluate` is correct while the process lives. Its inputs are not.
`actual fill`, `original initial stop` and position identity were RAM-only, so a
restart mid-position had two ways to be wrong and both are silent:

    ADOPT THE CURRENT VENUE STOP AS THE BASELINE. Protection is designed to
    move. Once it has, the working stop is no longer the original risk, and
    R recomputed from it shrinks every time the trade improves -- eventually
    reporting +1R on a position that has barely moved.

    FALL BACK TO THE REQUESTED ENTRY. On 2026-08-24 the request was 29092.25
    and the fill 29090.25. Against the same 29110.25 stop that is 18.00 points
    of requested risk and 20.00 of real risk: a restart using the request would
    protect at 0.9R.

INITIAL RISK IS IMMUTABLE. It is a fact about how the trade STARTED and nothing
that happens afterwards may rewrite it -- not an advance, not a restart, not a
re-adoption, not break-even having already been applied.

    initial_risk_baseline   actual fill · original initial stop · original R
                            frozen, reconstructed from durable evidence
    current_protection      the order working at the venue right now
                            expected to move, never a source of R

BOTH HALVES ALREADY EXIST ON DISK and this reads them rather than adding a
store: the trade mission carries the fill and position identity, the submission
ledger carries the authorized geometry, and `mission_id` joins them.

    THE RECORDED `stop_points` IS NOT R. The ledger wrote 18.0 for the trade
    above, because that is the requested-entry distance the sizing lane
    approved. R is recomputed here from `stop_price` against the FILL. Reading
    the stored number would be wrong by 10% on that specimen and wrong silently.

Pure reader. No broker, no network, no provider. Never raises.
"""
from __future__ import annotations

import json
import os

SCHEMA = "break_even_baseline.v1"

RECOVERED = "recovered"
UNAVAILABLE = "unavailable"

NO_MISSION = "no_trade_mission_record"
NO_FILL = "no_actual_fill_price"
NO_SUBMISSION = "no_submission_geometry"
NO_STOP = "no_original_initial_stop"
NOT_FILLED = "mission_never_filled"
DEGENERATE = "initial_risk_not_positive"
IDENTITY_MISMATCH = "mission_and_submission_disagree"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _side(direction):
    d = str(direction or "").strip().lower()
    if d in ("long", "buy", "bullish"):
        return "long"
    if d in ("short", "sell", "bearish"):
        return "short"
    return None


def load_mission(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def load_submission_geometry(path, mission_id):
    """The AUTHORIZED geometry for this mission, from the durable ledger.

    The ledger is append-only with several states per submission; the geometry
    is identical across them by construction, so the FIRST record for the
    mission is taken. Records for other missions are ignored rather than
    merged -- one position's stop is not another's.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if str(row.get("mission_id") or "") != str(mission_id):
                    continue
                geo = row.get("geometry")
                if isinstance(geo, dict) and geo:
                    return dict(geo, _submission_id=row.get("submission_id"),
                                _token_id=row.get("token_id"))
    except Exception:  # noqa: BLE001
        return None
    return None


def recover(*, mission_path, submissions_path) -> dict:
    """Reconstruct the immutable initial-risk baseline from durable evidence.

    Returns `status: recovered` with the frozen baseline, or `unavailable` with
    a named reason. NEVER returns a partially-guessed baseline: a break-even
    trigger computed from half-known risk is worse than no management at all,
    because it looks like management.
    """
    def out(status, reason=None, detail="", **extra):
        return dict({"schema": SCHEMA, "status": status, "reason": reason,
                     "detail": detail}, **extra)

    m = load_mission(mission_path)
    if not isinstance(m, dict) or not m:
        return out(UNAVAILABLE, NO_MISSION, str(mission_path))
    mission_id = m.get("mission_id")
    fill = _num(m.get("fill_price"))
    qty = m.get("filled_quantity")
    if fill is None or fill <= 0:
        return out(UNAVAILABLE, NO_FILL,
                   "the mission records no actual fill price; the requested "
                   "entry is never a substitute", mission_id=mission_id)
    try:
        if int(qty or 0) <= 0:
            return out(UNAVAILABLE, NOT_FILLED, f"filled_quantity={qty!r}",
                       mission_id=mission_id)
    except (TypeError, ValueError):
        return out(UNAVAILABLE, NOT_FILLED, f"filled_quantity={qty!r}",
                   mission_id=mission_id)

    geo = load_submission_geometry(submissions_path, mission_id)
    if not geo:
        return out(UNAVAILABLE, NO_SUBMISSION, f"mission {mission_id!r}",
                   mission_id=mission_id)
    stop = _num(geo.get("stop_price"))
    if stop is None:
        return out(UNAVAILABLE, NO_STOP, "submission carries no stop_price",
                   mission_id=mission_id)
    side = _side(geo.get("direction"))
    if side is None:
        return out(UNAVAILABLE, "unknown_direction",
                   f"direction {geo.get('direction')!r}", mission_id=mission_id)

    # IDENTITY IS CHECKED, NOT ASSUMED. Two durable artifacts joined by
    # mission_id must still agree about WHICH instrument and account this is,
    # or the baseline is being assembled from two different trades.
    for field, mv in (("contract_id", m.get("contract_id")),):
        gv = geo.get(field)
        if gv and mv and str(gv) != str(mv):
            return out(UNAVAILABLE, IDENTITY_MISMATCH,
                       f"{field}: mission {mv!r} vs submission {gv!r}",
                       mission_id=mission_id)

    # R FROM THE FILL, NEVER FROM THE RECORDED DISTANCE. `geometry.stop_points`
    # is the requested-entry distance the sizing lane approved (18.0 on the
    # 2026-08-24 trade); real risk against the fill was 20.00.
    risk = (fill - stop) if side == "long" else (stop - fill)
    if risk is None or risk <= 0:
        return out(UNAVAILABLE, DEGENERATE,
                   f"fill {fill} vs stop {stop} for {side}", mission_id=mission_id)

    return out(RECOVERED, None, "",
               mission_id=mission_id,
               direction=side,
               entry_fill_price=fill,
               original_initial_stop=stop,
               initial_risk_points=round(risk, 4),
               quantity=int(qty),
               contract_id=m.get("contract_id"),
               account_fingerprint=m.get("account_fingerprint"),
               entry_order_id=m.get("order_id"),
               token_id=m.get("token_id"),
               # Kept ONLY so a reader can see the divergence that makes this
               # module necessary. Never used to compute anything.
               recorded_requested_entry=_num(geo.get("entry_price")),
               recorded_stop_points_not_used=_num(geo.get("stop_points")))
