"""NEWS-2 Phase 1 — reconcile scheduled events, persist them, read them back.

RECONCILIATION NEVER ERASES A SOURCE. Records that name the same occurrence
(same category, same ET release day; Fed-chair appearances by exact time) are
grouped into one ScheduledEvent that keeps EVERY record. The highest-authority
record is primary. If records with a known time disagree, the event is a
CONFLICT and both times stay visible -- nothing picks a winner silently.

ABSENCE IS NOT CALM. `calendar_view` answers UNKNOWN when there is no snapshot,
STALE when the snapshot is older than allowed, and never produces a "normal" or
"no risk" verdict from missing data. This module holds facts, not risk verdicts.
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from news.factual import model as M

STORE_DIR = os.path.join("data", "news", "calendar")
#: A calendar older than this is STALE. A day covers the pre-arm refresh.
DEFAULT_MAX_AGE_SECONDS = 24 * 3600


def _group_key(category: str, record: M.SourceRecord) -> Optional[str]:
    when = M.parse_instant(record.scheduled_at)
    if when is not None:
        local = when.astimezone(M.ET)
        day = local.date().isoformat()
        if category == M.FED_CHAIR:          # several appearances a day are possible
            return f"{category}|{local.isoformat()}"
        return f"{category}|{day}"
    if record.convention_note and len(record.convention_note) == 10:
        return f"{category}|{record.convention_note}"      # date-only row
    return None


def reconcile(raw_events: list, source_status: dict) -> list:
    """Group raw source events into ScheduledEvents. Pure; keeps all provenance."""
    groups: dict = {}
    names: dict = {}
    for raw in raw_events:
        rec: M.SourceRecord = raw["record"]
        key = _group_key(raw["category"], rec)
        if key is None:
            continue
        groups.setdefault(key, []).append(rec)
        names.setdefault(key, (raw["category"], raw["name"]))

    out = []
    for key, recs in groups.items():
        category, fallback_name = names[key]
        recs = sorted(recs, key=lambda r: M.AUTHORITY_RANK.get(r.authority, 9))
        timed = [r for r in recs if r.scheduled_at]
        primary = timed[0] if timed else recs[0]

        # conflict: two DIFFERENT sources state different times
        by_source = {}
        for r in timed:
            by_source.setdefault(r.source_name, set()).add(r.scheduled_at)
        distinct_times = {t for times in by_source.values() for t in times}
        conflicts = []
        if len(by_source) > 1 and len(distinct_times) > 1:
            conflicts = [{"source": s, "scheduled_at": sorted(t)} for s, t in sorted(by_source.items())]
        n_sources = len({r.source_name for r in recs})
        cross = ("conflict" if conflicts
                 else "confirmed" if n_sources > 1 else "single_source")

        src_state = (source_status.get(primary.source_name) or {}).get("status")
        data_state = (M.CONFLICT if conflicts
                      else M.KNOWN if src_state == M.SOURCE_OK and primary.scheduled_at
                      else M.UNKNOWN)

        impact = next((r for r in recs if r.impact_class), None)
        valued = next((r for r in recs if any((r.actual, r.consensus, r.previous))), None)
        official_name = next((r.source_title for r in recs
                              if r.authority != M.AUTHORITY_CONVENIENCE and r.source_title), None)
        scheduled_at = primary.scheduled_at
        eid_basis = scheduled_at or key
        out.append(M.ScheduledEvent(
            event_id=M.event_id(category, eid_basis),
            name=official_name or fallback_name,
            category=category,
            scheduled_at=scheduled_at,
            timezone="America/New_York",
            scheduled_local=M.local_render(scheduled_at),
            primary_source=primary.source_name,
            primary_authority=primary.authority,
            time_basis=primary.time_basis,
            data_state=data_state,
            cross_check_status=cross,
            impact_class=impact.impact_class if impact else None,
            impact_class_source=impact.source_name if impact else None,
            actual=valued.actual if valued else None,
            consensus=valued.consensus if valued else None,
            previous=valued.previous if valued else None,
            values_source=valued.source_name if valued else None,
            sources=[r.to_dict() for r in recs],
            conflicts=conflicts))
    out.sort(key=lambda e: (e.scheduled_at or "9999", e.category))
    return out


def build_calendar_state(results: list, *, now: datetime) -> dict:
    """`results` is a list of (SourceStatus, raw_events) from the adapters."""
    statuses = {s.source_name: s.to_dict() for s, _ in results}
    raw = [e for _, evs in results for e in evs]
    events = reconcile(raw, statuses)
    ok = [s for s in statuses.values() if s["status"] == M.SOURCE_OK]
    authoritative_ok = [s for s in ok if s["authority"] != M.AUTHORITY_CONVENIENCE]
    if not ok:
        state, reason = M.UNKNOWN, "no source returned usable data"
    elif not authoritative_ok:
        state, reason = M.UNKNOWN, ("only the convenience feed answered; "
                                    "no official or backstop source confirms the schedule")
    else:
        state, reason = M.KNOWN, None
    return {
        "schema_version": M.SCHEMA_CALENDAR,
        "built_at": M.iso(now),
        "data_state": state,
        "data_state_reason": reason,
        "authority": "observe_only",
        "brain_input": False,
        "sources": list(statuses.values()),
        "degraded_sources": [s["source_name"] for s in statuses.values()
                             if s["status"] != M.SOURCE_OK],
        "conflict_count": sum(1 for e in events if e.data_state == M.CONFLICT),
        "events": [e.to_dict() for e in events],
    }


# ── persistence ──────────────────────────────────────────────────────────────
def persist(state: dict, store_dir: str = STORE_DIR) -> str:
    os.makedirs(store_dir, exist_ok=True)
    built = M.parse_instant(state["built_at"]).astimezone(M.ET)
    path = os.path.join(store_dir, f"calendar_state_{built:%Y%m%dT%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, default=str)
    return path


def load_latest(store_dir: str = STORE_DIR, *, at: datetime = None) -> Optional[dict]:
    """The newest snapshot built at or before `at` (default: newest). Never raises."""
    try:
        paths = sorted(glob.glob(os.path.join(store_dir, "calendar_state_*.json")))
        for path in reversed(paths):
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
            built = M.parse_instant(state.get("built_at"))
            if at is None or (built is not None and built <= at):
                state["_path"] = path
                return state
    except Exception:  # noqa: BLE001
        return None
    return None


# ── read side: facts only, never a calm verdict ──────────────────────────────
def calendar_view(state: Optional[dict], now: datetime, *,
                  max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
                  horizon_hours: float = 24.0) -> dict:
    if not state:
        return {"data_state": M.UNKNOWN, "reason": "no calendar snapshot exists",
                "as_of": None, "age_seconds": None, "events": []}
    age = M.age_seconds(state.get("built_at"), now)
    fresh = M.freshness(state.get("built_at"), now, max_age_seconds)
    if state.get("data_state") != M.KNOWN:
        data_state, reason = state.get("data_state") or M.UNKNOWN, state.get("data_state_reason")
    elif fresh != M.KNOWN:
        data_state, reason = fresh, f"snapshot is {age}s old (max {max_age_seconds:g}s)"
    else:
        data_state, reason = M.KNOWN, None
    lo, hi = now - timedelta(hours=2), now + timedelta(hours=horizon_hours)
    upcoming = []
    for e in state.get("events") or []:
        t = M.parse_instant(e.get("scheduled_at"))
        if t is not None and lo <= t <= hi:
            ev = dict(e)
            ev["minutes_from_now"] = round((t - now).total_seconds() / 60.0, 1)
            upcoming.append(ev)
    return {"data_state": data_state, "reason": reason,
            "as_of": state.get("built_at"), "age_seconds": age,
            "degraded_sources": state.get("degraded_sources") or [],
            "events": upcoming}


# ── event-window MEASUREMENT (observe-only; blocks nothing) ──────────────────
DEFAULT_WINDOWS = ((-15, 15), (-10, 5), (-5, 5))


def event_window_facts(ts: datetime, state: Optional[dict], *,
                       windows=DEFAULT_WINDOWS) -> dict:
    """Which scheduled events fell inside each window around `ts`.

    A window (a, b) means: an event scheduled between a and b minutes RELATIVE
    TO THE EVENT of the decision -- i.e. the decision happened from |a| minutes
    before the event to b minutes after it. Measurement only.
    """
    if not state:
        return {"data_state": M.UNKNOWN, "reason": "no calendar snapshot", "windows": {}}
    out = {}
    for a, b in windows:
        hits = []
        for e in state.get("events") or []:
            t = M.parse_instant(e.get("scheduled_at"))
            if t is None:
                continue
            rel = (ts - t).total_seconds() / 60.0     # + = after the event
            if a <= rel <= b:
                hits.append({"event_id": e["event_id"], "name": e["name"],
                             "category": e["category"], "scheduled_at": e["scheduled_at"],
                             "minutes_relative_to_event": round(rel, 1),
                             "analysis_tier1": e["category"] in M.ANALYSIS_TIER1,
                             "impact_class": e.get("impact_class"),
                             "data_state": e.get("data_state")})
        out[f"{a:+d}/{b:+d}"] = {"inside": bool(hits), "events": hits}
    return {"data_state": state.get("data_state"), "as_of": state.get("built_at"),
            "windows": out}
