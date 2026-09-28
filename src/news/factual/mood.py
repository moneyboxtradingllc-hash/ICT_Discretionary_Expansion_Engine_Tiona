"""NEWS-2 Phase 3b — market-mood FACTS. Observe-only; never raises.

  * MNQ overnight / premarket move from TopstepX 1m bars the bot already reads.
  * VIX, VXN and the U.S. 10-year yield from FRED daily series.

FRED values are DAILY CLOSES published after the fact. They are carried with
`observation_date`, `source_cadence = "daily_close"` and an age in days, and are
labelled `delayed_daily_close`. Nothing here ever calls them live or current:
the field that would say so does not exist.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Optional

from news.factual import model as M
from news.factual.http import fetch_text, redact

FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_SERIES = {"VIXCLS": "CBOE Volatility Index (VIX), daily close",
               "VXNCLS": "CBOE Nasdaq-100 Volatility Index (VXN), daily close",
               "DGS10": "10-Year Treasury Constant Maturity, daily"}

#: The CME equity-index RTH close the overnight move is measured from.
RTH_CLOSE_ET = time(16, 0)


def _prior_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def parse_fred_observations(series_id: str, text: str, *, fetched_at: str,
                            reference: str, now: datetime) -> dict:
    payload = json.loads(text)
    obs = payload.get("observations")
    if not isinstance(obs, list):
        raise ValueError("no observations array")
    latest = None
    for o in obs:                       # requested newest-first; skip FRED's "." gaps
        v = str((o or {}).get("value", "")).strip()
        if v and v != ".":
            try:
                latest = (date.fromisoformat(o["date"]), float(v))
                break
            except (KeyError, ValueError):
                continue
    base = {"series_id": series_id, "description": FRED_SERIES.get(series_id),
            "source_name": "fred_series_observations", "reference": reference,
            "fetched_at": fetched_at, "source_cadence": "daily_close",
            "timeliness": "delayed_daily_close"}
    if latest is None:
        return {**base, "data_state": M.UNKNOWN, "reason": "no numeric observation",
                "value": None, "observation_date": None, "age_days": None}
    obs_date, value = latest
    today_et = now.astimezone(M.ET).date()
    age_days = (today_et - obs_date).days
    # The newest close that COULD exist is the prior weekday's. Older is stale.
    state = M.KNOWN if obs_date >= _prior_weekday(today_et) else M.STALE
    return {**base, "data_state": state,
            "reason": None if state == M.KNOWN else f"latest observation is {age_days} day(s) old",
            "value": value, "observation_date": obs_date.isoformat(), "age_days": age_days}


def fetch_fred_series(series_id: str, *, api_key: Optional[str],
                      fetch: Callable = fetch_text, now: datetime = None) -> dict:
    now = now or M.utc_now()
    base = {"series_id": series_id, "description": FRED_SERIES.get(series_id),
            "source_name": "fred_series_observations", "fetched_at": M.iso(now),
            "source_cadence": "daily_close", "timeliness": "delayed_daily_close",
            "value": None, "observation_date": None, "age_days": None}
    if not api_key:
        return {**base, "data_state": M.UNKNOWN, "status": M.SOURCE_UNAVAILABLE,
                "reason": "FRED_API_KEY not set", "reference": FRED_OBS_URL}
    url = (f"{FRED_OBS_URL}?series_id={series_id}&api_key={api_key}"
           f"&file_type=json&sort_order=desc&limit=10")
    res = fetch(url)
    if not res.get("ok"):
        return {**base, "data_state": M.UNKNOWN, "status": M.SOURCE_FAILED,
                "reason": res.get("error"), "reference": redact(url)}
    try:
        out = parse_fred_observations(series_id, res.get("text") or "",
                                      fetched_at=M.iso(now), reference=redact(url), now=now)
        out["status"] = M.SOURCE_OK if out["data_state"] != M.UNKNOWN else M.SOURCE_EMPTY
        return out
    except Exception as exc:  # noqa: BLE001
        return {**base, "data_state": M.UNKNOWN, "status": M.SOURCE_PARSE_FAILED,
                "reason": f"{type(exc).__name__}: {exc}", "reference": redact(url)}


def mnq_overnight_move(bars: list, *, now: datetime, fetched_at: str = None) -> dict:
    """Last price vs the prior session's 16:00 ET close, from 1m bars.

    `bars` are TopstepX 1m bars ({"timestamp", "close"}), oldest first. Both
    anchors must be PRESENT in the bars; nothing is interpolated.
    """
    base = {"source_name": "topstepx_1m_bars", "fetched_at": fetched_at or M.iso(now),
            "anchor": "prior session 16:00 ET close", "timeliness": "bar_close"}
    parsed = []
    for b in bars or []:
        t = M.parse_instant((b or {}).get("timestamp"))
        try:
            c = float(b.get("close"))
        except (TypeError, ValueError, AttributeError):
            continue
        if t is not None:
            parsed.append((t, c))
    parsed.sort()
    if not parsed:
        return {**base, "data_state": M.UNKNOWN, "reason": "no bars"}
    today_et = now.astimezone(M.ET).date()
    prior = _prior_weekday(today_et)
    close_at = datetime.combine(prior, RTH_CLOSE_ET, tzinfo=M.ET).astimezone(timezone.utc)
    # the bar that CLOSES at 16:00 ET opens at 15:59
    anchor = next((c for t, c in parsed if t == close_at - timedelta(minutes=1)), None)
    last_t, last_c = parsed[-1]
    if anchor is None:
        return {**base, "data_state": M.UNKNOWN,
                "reason": f"no bar for {prior} 15:59-16:00 ET in the supplied history",
                "last_price": last_c, "last_bar_at": M.iso(last_t)}
    move = round(last_c - anchor, 2)
    age = (now - last_t).total_seconds()
    return {**base, "data_state": M.KNOWN if age <= 180 else M.STALE,
            "reason": None if age <= 180 else f"last bar is {age:.0f}s old",
            "prior_close": anchor, "prior_close_at": M.iso(close_at),
            "last_price": last_c, "last_bar_at": M.iso(last_t),
            "move_points": move, "move_pct": round(100.0 * move / anchor, 3)}


def build_mood(*, bars: list, api_key: Optional[str], fetch: Callable = fetch_text,
               now: datetime = None) -> dict:
    now = now or M.utc_now()
    return {"schema_version": "news2.market_mood.v1", "built_at": M.iso(now),
            "authority": "observe_only", "brain_input": False,
            "mnq_overnight": mnq_overnight_move(bars, now=now),
            "series": {sid: fetch_fred_series(sid, api_key=api_key, fetch=fetch, now=now)
                       for sid in FRED_SERIES}}
