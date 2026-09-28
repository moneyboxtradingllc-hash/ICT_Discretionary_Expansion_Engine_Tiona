"""A minimal, strict iCalendar (RFC 5545) VEVENT reader. Pure; never raises.

Only what an agency release calendar uses: line unfolding, VEVENT blocks,
SUMMARY/UID/DTSTART/DTSTAMP/LAST-MODIFIED, and DTSTART as UTC ("...Z"), with a
TZID, or as a bare DATE. An unrecognised TZID is REFUSED rather than guessed:
a release time interpreted in the wrong zone is worse than no time at all.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

#: TZID spellings seen on U.S. agency calendars that unambiguously mean ET.
_EASTERN_TZIDS = {"america/new_york", "us-eastern", "us/eastern", "eastern standard time",
                  "eastern time", "(utc-05:00) eastern time (us & canada)"}


def _unfold(text: str) -> list:
    lines = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _split(line: str) -> tuple:
    """'DTSTART;TZID=US-Eastern:20261014T083000' -> ('DTSTART', {'TZID': ...}, value)."""
    head, _, value = line.partition(":")
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def _unescape(v: str) -> str:
    return (v.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",")
             .replace("\\;", ";").replace("\\\\", "\\")).strip()


def parse_dt(value: str, params: dict) -> dict:
    """{'instant': aware UTC datetime|None, 'date': date|None, 'zone': str|None, 'error': str|None}."""
    v = (value or "").strip()
    out = {"instant": None, "date": None, "zone": None, "error": None}
    try:
        if params.get("VALUE", "").upper() == "DATE" or (len(v) == 8 and v.isdigit()):
            out["date"] = date(int(v[:4]), int(v[4:6]), int(v[6:8]))
            return out
        if v.endswith("Z"):
            dt = datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            out["instant"], out["zone"] = dt, "UTC"
            out["date"] = dt.date()
            return out
        naive = datetime.strptime(v, "%Y%m%dT%H%M%S")
        tzid = (params.get("TZID") or "").strip()
        if tzid.lower() in _EASTERN_TZIDS:
            zone = "America/New_York"
        else:
            try:
                ZoneInfo(tzid)
                zone = tzid
            except Exception:  # noqa: BLE001
                out["error"] = f"unrecognised TZID {tzid!r}" if tzid else "floating time (no TZID)"
                return out
        local = naive.replace(tzinfo=ZoneInfo(zone))
        out["instant"] = local.astimezone(timezone.utc)
        out["zone"], out["date"] = zone, local.date()
        return out
    except (ValueError, TypeError) as exc:
        out["error"] = f"unparseable DTSTART {v!r}: {exc}"
        return out


def parse_vevents(text: str) -> list:
    """Every VEVENT as a dict. Never raises; a malformed event carries 'error'."""
    events, cur = [], None
    for line in _unfold(text):
        if not line.strip():
            continue
        name, params, value = _split(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            cur = {"summary": None, "uid": None, "dtstart": None,
                   "dtstamp": None, "last_modified": None, "error": None}
        elif name == "END" and value.upper() == "VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None:
            if name == "SUMMARY":
                cur["summary"] = _unescape(value)
            elif name == "UID":
                cur["uid"] = value.strip()
            elif name == "DTSTART":
                cur["dtstart"] = parse_dt(value, params)
                if cur["dtstart"]["error"]:
                    cur["error"] = cur["dtstart"]["error"]
            elif name in ("DTSTAMP", "LAST-MODIFIED"):
                parsed = parse_dt(value, params)
                key = "dtstamp" if name == "DTSTAMP" else "last_modified"
                cur[key] = parsed["instant"].isoformat() if parsed["instant"] else None
    return events


def first_instant(ev: dict) -> Optional[datetime]:
    d = (ev or {}).get("dtstart") or {}
    return d.get("instant")
