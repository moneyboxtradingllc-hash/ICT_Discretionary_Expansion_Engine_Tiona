"""Read-only volume-profile evidence derived only from sealed GatewayTrade VAP.

This module deliberately has no route to Brain input, qualification, risk, or
execution.  It turns already durable, continuity-classified minute x price
volume into a descriptive prior-RTH profile; it never manufactures VAP from
OHLCV.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from market_data import vap_store as STORE
from market_data import venue_calendar as VC

VALUE_AREA_FRACTION = 0.70
RTH_START_MINUTE = 9 * 60 + 30
RTH_END_MINUTE = 16 * 60


class VolumeAtPriceCollector:
    """Compatibility-facing owner for the existing proven GatewayTrade capture.

    The collector is intentionally a thin composition rather than a second tape
    implementation: ``VapCaptureProvider`` already provides the required
    contract-bound, batch-replay-only, durable minute aggregation on the one
    shared market runtime.
    """
    def __new__(cls, *, contract_id, tick_size, store_dir, instrument="MNQ", clock=None):
        from market_data.vap_provider import VapCaptureProvider
        return VapCaptureProvider(contract_id=contract_id, tick_size=tick_size,
                                  store_dir=store_dir, instrument=instrument, clock=clock)


def _utc(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def profile_from_minutes(records, *, start, end, value_area_fraction=VALUE_AREA_FRACTION):
    """Pure profile over the explicit half-open UTC interval ``[start, end)``."""
    start, end = _utc(start), _utc(end)
    if start is None or end is None or end <= start:
        return {"available": False, "reason": "INVALID_INTERVAL"}
    levels = {}
    tick_size = None
    for row in records or []:
        minute = _utc(row.get("minute")) if isinstance(row, dict) else None
        if minute is None or not start <= minute < end or row.get("status") != STORE.COMPLETE:
            continue
        tick_size = tick_size or row.get("tick_size")
        for index, volume in (row.get("levels") or {}).items():
            try:
                price, vol = float(index) * float(row["tick_size"]), float(volume)
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(price) and math.isfinite(vol) and vol > 0:
                levels[price] = levels.get(price, 0.0) + vol
    total = sum(levels.values())
    if total <= 0:
        return {"available": False, "reason": "NO_COMPLETE_TRADED_VOLUME",
                "start": start.isoformat(), "end": end.isoformat(), "total_volume": 0.0}
    vwap = sum(price * volume for price, volume in levels.items()) / total
    max_volume = max(levels.values())
    poc = min((price for price, volume in levels.items() if volume == max_volume),
              key=lambda price: (round(abs(price - vwap), 12), price))
    tick = float(tick_size or 0.0)
    included, accumulated = {poc}, levels[poc]
    # Only immediately adjacent *traded* ticks can extend a contiguous value
    # area.  We never bridge an untraded gap by inventing zero-volume levels.
    while accumulated / total < float(value_area_fraction) and tick > 0:
        lo, hi = min(included) - tick, max(included) + tick
        lv, hv = levels.get(lo, 0.0), levels.get(hi, 0.0)
        if lv <= 0 and hv <= 0:
            break
        if lv == hv:
            included.update(p for p, v in ((lo, lv), (hi, hv)) if v > 0)
            accumulated += lv + hv
        elif lv > hv:
            included.add(lo); accumulated += lv
        else:
            included.add(hi); accumulated += hv
    return {"available": True, "start": start.isoformat(), "end": end.isoformat(),
            "total_volume": total, "levels_count": len(levels), "poc": poc,
            "poc_volume": levels[poc], "vwap": vwap, "val": min(included),
            "vah": max(included), "value_area_fraction": float(value_area_fraction),
            "value_area_achieved_fraction": accumulated / total,
            "concentration": levels[poc] / total, "evidence_source": "topstepx_gateway_trade"}


def prior_completed_rth_profile(*, store_dir, contract_id, instrument="MNQ", now=None):
    """Return prior completed NY RTH only when every expected minute is durable."""
    now = _utc(now or datetime.now(timezone.utc))
    eastern = VC.EASTERN
    today = now.astimezone(eastern).date()
    # A session is completed only after 16:00 ET.  Walk back over calendar days;
    # the venue calendar remains the authority on whether a minute was expected.
    candidate = today if now.astimezone(eastern).hour * 60 + now.astimezone(eastern).minute >= RTH_END_MINUTE else today - timedelta(days=1)
    for _ in range(14):
        start_et = eastern.localize(datetime.combine(candidate, datetime.min.time())).replace(hour=9, minute=30)
        end_et = eastern.localize(datetime.combine(candidate, datetime.min.time())).replace(hour=16, minute=0)
        start, end = start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)
        expected = [start + timedelta(minutes=i) for i in range(390)
                    if VC.is_expected(start + timedelta(minutes=i), instrument)]
        if expected:
            rows = STORE.load(store_dir, contract_id, since=start.isoformat())
            observed = {(_utc(r.get("minute"))).isoformat() for r in rows
                        if _utc(r.get("minute")) in set(expected) and r.get("status") == STORE.COMPLETE}
            missing = [m.isoformat() for m in expected if m.isoformat() not in observed]
            base = {"session_date": candidate.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
                    "expected_minutes": len(expected), "observed_vap_minutes": len(observed),
                    "missing_minutes": missing, "complete": not missing}
            if missing:
                return {**base, "available": False, "reason": "INCOMPLETE_RTH_VAP_COVERAGE"}
            return {**base, **profile_from_minutes(rows, start=start, end=end), "complete": True}
        candidate -= timedelta(days=1)
    return {"available": False, "reason": "NO_CALENDAR_AUTHORIZED_PRIOR_RTH"}


def with_price_location(profile, price):
    out = dict(profile or {})
    try:
        price = float(price)
    except (TypeError, ValueError):
        return out
    if not out.get("available") or not math.isfinite(price):
        out["price_location"] = "UNKNOWN"
        return out
    out["price_location"] = "below_value" if price < out["val"] else ("above_value" if price > out["vah"] else "inside_value")
    for key in ("poc", "vah", "val"):
        out[f"distance_to_{key}_points"] = price - out[key]
    return out
