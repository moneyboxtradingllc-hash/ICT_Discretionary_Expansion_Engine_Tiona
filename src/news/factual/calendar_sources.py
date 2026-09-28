"""NEWS-2 Phase 1 — scheduled-event SOURCE adapters. Parse only; never raise.

Authority, per the owner's ruling (2026-09-27):

    OFFICIAL     the releasing agency's own schedule          authoritative
                 - BLS release calendar (iCalendar): CPI, PPI, Employment Situation
                 - Federal Reserve FOMC calendar page: FOMC decisions
    BACKSTOP     FRED release metadata (dates only)            supplemental
                 - GDP / PCE (BEA), Retail Sales (Census), Jobless Claims (DOL),
                   and a second date for the official releases above
    CONVENIENCE  ForexFactory weekly JSON                      cross-check only
                 - the only source here for ISM, Fed-chair appearances and
                   FOMC minutes, which therefore stay `single_source`

A release TIME is recorded as `source_explicit` only when the source states it.
When a source gives only a DATE, the agency's standing release time is applied
and recorded as `agency_convention`, with the convention named -- never passed
off as the source's own statement. Conflicts with the convenience feed then
stay visible instead of being assumed away.

Every adapter returns (SourceStatus, [raw event dicts]); a raw event is
{"category", "name", "record": SourceRecord}.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timezone
from typing import Callable, Optional

from news.factual import ics
from news.factual import model as M
from news.factual.http import fetch_text, redact

BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
FED_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FRED_RELEASE_DATES_URL = "https://api.stlouisfed.org/fred/releases/dates"
FF_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

#: Standing release times in ET, applied ONLY to a sourced date, and labelled.
CONVENTION_ET = {
    M.CPI: (time(8, 30), "BLS: CPI releases at 8:30 a.m. ET"),
    M.PPI: (time(8, 30), "BLS: PPI releases at 8:30 a.m. ET"),
    M.NFP: (time(8, 30), "BLS: Employment Situation releases at 8:30 a.m. ET"),
    M.GDP: (time(8, 30), "BEA: GDP releases at 8:30 a.m. ET"),
    M.PCE: (time(8, 30), "BEA: Personal Income and Outlays releases at 8:30 a.m. ET"),
    M.RETAIL_SALES: (time(8, 30), "Census: Advance Retail Sales releases at 8:30 a.m. ET"),
    M.JOBLESS_CLAIMS: (time(8, 30), "DOL: weekly claims release at 8:30 a.m. ET"),
    M.FOMC_DECISION: (time(14, 0), "FOMC: policy statement releases at 2:00 p.m. ET"),
}

TERMS = {
    "bls_ics": "U.S. government data (public domain); BLS asks automated clients to send a descriptive User-Agent.",
    "fed_fomc": "U.S. government page (public domain); HTML layout is not a stable API -- parse failure is reported, never guessed.",
    "fred_release_dates": "Free FRED API key required (FRED_API_KEY); FRED terms of use apply.",
    "forexfactory": "Unofficial public calendar export; rate-limited; convenience/cross-check only, never sole authority.",
}


def _status(name, status, authority, *, fetched_at, reason=None, reference=None,
            count=0, terms=None) -> M.SourceStatus:
    return M.SourceStatus(source_name=name, status=status, authority=authority,
                          fetched_at=fetched_at, reason=reason, reference=reference,
                          record_count=count, terms_note=terms)


def _convention_instant(category: str, d: date) -> tuple:
    t, note = CONVENTION_ET[category]
    local = datetime.combine(d, t, tzinfo=M.ET)
    return local.astimezone(timezone.utc), note


# ── BLS (official): CPI, PPI, Employment Situation ───────────────────────────
_BLS_TITLES = (
    ("consumer price index", M.CPI, "Consumer Price Index"),
    ("producer price index", M.PPI, "Producer Price Index"),
    ("employment situation", M.NFP, "Employment Situation"),
)


def parse_bls_ics(text: str, *, fetched_at: str, reference: str) -> tuple:
    events, bad = [], 0
    for ev in ics.parse_vevents(text):
        summary = (ev.get("summary") or "").strip()
        low = summary.lower()
        match = next((c for c in _BLS_TITLES if low.startswith(c[0])), None)
        if not match:
            continue
        _, category, name = match
        dt = ev.get("dtstart") or {}
        if ev.get("error") or not (dt.get("instant") or dt.get("date")):
            bad += 1
            continue
        if dt.get("instant"):
            instant, basis, note = dt["instant"], M.TIME_SOURCE_EXPLICIT, None
        else:
            instant, note = _convention_instant(category, dt["date"])
            basis = M.TIME_AGENCY_CONVENTION
        events.append({"category": category, "name": name, "record": M.SourceRecord(
            source_name="bls_ics", authority=M.AUTHORITY_OFFICIAL, reference=reference,
            fetched_at=fetched_at, scheduled_at=M.iso(instant), time_basis=basis,
            source_title=summary, source_published_at=ev.get("last_modified") or ev.get("dtstamp"),
            convention_note=note)})
    return events, bad


# ── Federal Reserve (official): FOMC decisions ───────────────────────────────
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_YEAR_RE = re.compile(r"(\d{4})\s+FOMC\s+Meetings", re.I)
_MONTH_RE = re.compile(r'fomc-meeting__month[^>]*>(?:\s*<[^>]+>)*\s*([A-Za-z]+(?:\s*/\s*[A-Za-z]+)?)', re.I)
_DATE_RE = re.compile(r'fomc-meeting__date[^>]*>(?:\s*<[^>]+>)*\s*([^<]+)', re.I)
_RANGE_RE = re.compile(r"(\d{1,2})\s*[-–]\s*(\d{1,2})")


def parse_fed_fomc_html(html: str, *, fetched_at: str, reference: str) -> tuple:
    """Scheduled FOMC decision days, one per meeting. Unscheduled/notation votes skipped."""
    events, skipped = [], 0
    text = html or ""
    marks = [(m.start(), int(m.group(1))) for m in _YEAR_RE.finditer(text)]
    for i, (start, year) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        seg = text[start:end]
        months = [m.group(1) for m in _MONTH_RE.finditer(seg)]
        dates = [m.group(1).strip() for m in _DATE_RE.finditer(seg)]
        for mon_text, date_text in zip(months, dates):
            low = date_text.lower()
            rng = _RANGE_RE.search(date_text)
            if "notation" in low or "unscheduled" in low or not rng:
                skipped += 1
                continue
            d1, d2 = int(rng.group(1)), int(rng.group(2))
            parts = [p.strip()[:3].lower() for p in mon_text.split("/")]
            month = _MONTHS.get(parts[-1] if (len(parts) > 1 and d2 < d1) else parts[0])
            if month is None:
                skipped += 1
                continue
            try:
                decision = date(year, month, d2)
            except ValueError:
                skipped += 1
                continue
            instant, note = _convention_instant(M.FOMC_DECISION, decision)
            events.append({"category": M.FOMC_DECISION, "name": "FOMC policy decision",
                           "record": M.SourceRecord(
                               source_name="fed_fomc", authority=M.AUTHORITY_OFFICIAL,
                               reference=reference, fetched_at=fetched_at,
                               scheduled_at=M.iso(instant),
                               time_basis=M.TIME_AGENCY_CONVENTION,
                               source_title=f"{mon_text} {date_text} {year}".strip(),
                               convention_note=note)})
    return events, skipped


# ── FRED release metadata (backstop, dates only) ─────────────────────────────
#: FRED release names -> category. Matched case-insensitively and EXACTLY:
#: an unfamiliar name is ignored and counted, never fuzzily assigned.
FRED_RELEASE_NAMES = {
    "consumer price index": M.CPI,
    "producer price index": M.PPI,
    "employment situation": M.NFP,
    "gross domestic product": M.GDP,
    "personal income and outlays": M.PCE,
    "advance monthly sales for retail and food services": M.RETAIL_SALES,
    "unemployment insurance weekly claims report": M.JOBLESS_CLAIMS,
    "unemployment insurance weekly claims": M.JOBLESS_CLAIMS,
    "fomc press release": M.FOMC_DECISION,
}


def parse_fred_release_dates(text: str, *, fetched_at: str, reference: str) -> tuple:
    payload = json.loads(text)
    rows = payload.get("release_dates")
    if not isinstance(rows, list):
        raise ValueError("no release_dates array")
    events, unmapped = [], 0
    for r in rows:
        name = str((r or {}).get("release_name") or "").strip()
        category = FRED_RELEASE_NAMES.get(name.lower())
        if category is None:
            unmapped += 1
            continue
        try:
            d = date.fromisoformat(str(r.get("date")))
        except (TypeError, ValueError):
            unmapped += 1
            continue
        instant, note = _convention_instant(category, d)
        events.append({"category": category, "name": name, "record": M.SourceRecord(
            source_name="fred_release_dates", authority=M.AUTHORITY_BACKSTOP,
            reference=reference, fetched_at=fetched_at, scheduled_at=M.iso(instant),
            time_basis=M.TIME_AGENCY_CONVENTION,
            source_title=f"{name} (release_id {r.get('release_id')})",
            convention_note=note)})
    return events, unmapped


# ── ForexFactory weekly JSON (convenience / cross-check) ─────────────────────
#: (title predicate, category, is_headline_row). Values (actual/forecast/
#: previous) are carried only from the headline row of each release.
_FF_RULES = (
    (lambda t: t.startswith("fomc meeting minutes"), M.FOMC_MINUTES, True),
    (lambda t: t.startswith("fomc press conference"), M.FED_CHAIR, False),
    (lambda t: t.startswith("fed chair") or "powell" in t, M.FED_CHAIR, True),
    (lambda t: t.startswith("federal funds rate"), M.FOMC_DECISION, True),
    (lambda t: t.startswith("fomc statement") or t.startswith("fomc economic projections"),
     M.FOMC_DECISION, False),
    (lambda t: t.startswith("core pce") or t.startswith("pce "), M.PCE, None),
    (lambda t: "cpi" in t.split(), M.CPI, None),
    (lambda t: "ppi" in t.split(), M.PPI, None),
    (lambda t: t.startswith("non-farm employment change"), M.NFP, True),
    (lambda t: t.startswith("unemployment rate") or t.startswith("average hourly earnings"),
     M.NFP, False),
    (lambda t: "gdp" in t.split(), M.GDP, None),
    (lambda t: t.startswith("ism "), M.ISM, None),
    (lambda t: t.startswith("core retail sales") or t.startswith("retail sales"),
     M.RETAIL_SALES, None),
    (lambda t: t.startswith("unemployment claims"), M.JOBLESS_CLAIMS, True),
)
_FF_HEADLINE_TITLES = {"cpi m/m", "ppi m/m", "core pce price index m/m",
                       "advance gdp q/q", "prelim gdp q/q", "final gdp q/q",
                       "retail sales m/m", "ism manufacturing pmi", "ism services pmi"}


def _ff_category(title: str) -> tuple:
    t = title.lower().strip()
    for pred, cat, headline in _FF_RULES:
        if pred(t):
            is_head = headline if headline is not None else (t in _FF_HEADLINE_TITLES)
            return cat, is_head
    return None, False


def parse_forexfactory(text: str, *, fetched_at: str, reference: str) -> tuple:
    rows = json.loads(text)
    if not isinstance(rows, list):
        raise ValueError("expected a JSON array")
    events, ignored = [], 0
    for r in rows:
        if not isinstance(r, dict) or str(r.get("country", "")).upper() != "USD":
            ignored += 1
            continue
        title = str(r.get("title") or "").strip()
        category, headline = _ff_category(title)
        when = M.parse_instant(r.get("date"))
        if category is None or when is None:
            ignored += 1
            continue
        local = when.astimezone(M.ET)
        date_only = local.time() == time(0, 0)       # FF writes "all day"/tentative at midnight
        impact = str(r.get("impact") or "").strip()
        events.append({"category": category, "name": title, "record": M.SourceRecord(
            source_name="forexfactory", authority=M.AUTHORITY_CONVENIENCE,
            reference=reference, fetched_at=fetched_at,
            scheduled_at=None if date_only else M.iso(when),
            time_basis=("source_date_only" if date_only else M.TIME_SOURCE_EXPLICIT),
            source_title=title,
            impact_class=impact.lower() if impact.lower() in ("high", "medium", "low") else None,
            actual=(r.get("actual") if headline else None) or None,
            consensus=(r.get("forecast") if headline else None) or None,
            previous=(r.get("previous") if headline else None) or None,
            convention_note=(local.date().isoformat() if date_only else None))})
    return events, ignored


# ── fetch + parse, with the failure made explicit ────────────────────────────
def _run(name, authority, url, parser, *, fetch, now, terms, headers=None):
    fetched_at = M.iso(now)
    ref = redact(url)
    res = fetch(url, headers=headers) if headers else fetch(url)
    if not res.get("ok"):
        return _status(name, M.SOURCE_FAILED, authority, fetched_at=fetched_at,
                       reason=res.get("error") or "fetch failed", reference=ref,
                       terms=terms), []
    try:
        events, dropped = parser(res.get("text") or "", fetched_at=fetched_at, reference=ref)
    except Exception as exc:  # noqa: BLE001 -- a malformed feed is a fact
        return _status(name, M.SOURCE_PARSE_FAILED, authority, fetched_at=fetched_at,
                       reason=f"{type(exc).__name__}: {exc}", reference=ref,
                       terms=terms), []
    if not events:
        return _status(name, M.SOURCE_EMPTY, authority, fetched_at=fetched_at,
                       reason=f"no usable events ({dropped} skipped)", reference=ref,
                       terms=terms), []
    return _status(name, M.SOURCE_OK, authority, fetched_at=fetched_at,
                   reason=(f"{dropped} row(s) skipped" if dropped else None),
                   reference=ref, count=len(events), terms=terms), events


def fetch_bls(*, fetch: Callable = fetch_text, now: datetime = None) -> tuple:
    return _run("bls_ics", M.AUTHORITY_OFFICIAL, BLS_ICS_URL, parse_bls_ics,
                fetch=fetch, now=now or M.utc_now(), terms=TERMS["bls_ics"])


def fetch_fed_fomc(*, fetch: Callable = fetch_text, now: datetime = None) -> tuple:
    now = now or M.utc_now()
    status, events = _run("fed_fomc", M.AUTHORITY_OFFICIAL, FED_FOMC_URL,
                          parse_fed_fomc_html, fetch=fetch, now=now,
                          terms=TERMS["fed_fomc"])
    # A page that parses but yields nothing for THIS year is not a calendar.
    if status.status == M.SOURCE_OK and not any(
            M.parse_instant(e["record"].scheduled_at).year == now.year for e in events):
        status.status = M.SOURCE_PARSE_FAILED
        status.reason = f"no {now.year} meetings found in the page"
        return status, []
    return status, events


def fetch_fred(*, api_key: Optional[str], fetch: Callable = fetch_text,
               now: datetime = None, days_ahead: int = 14) -> tuple:
    now = now or M.utc_now()
    if not api_key:
        return _status("fred_release_dates", M.SOURCE_UNAVAILABLE, M.AUTHORITY_BACKSTOP,
                       fetched_at=M.iso(now), reason="FRED_API_KEY not set",
                       reference=FRED_RELEASE_DATES_URL,
                       terms=TERMS["fred_release_dates"]), []
    from datetime import timedelta
    start = (now - timedelta(days=1)).date().isoformat()
    end = (now + timedelta(days=days_ahead)).date().isoformat()
    url = (f"{FRED_RELEASE_DATES_URL}?api_key={api_key}&file_type=json"
           f"&realtime_start={start}&realtime_end={end}"
           f"&include_release_dates_with_no_data=true&sort_order=asc&limit=1000")
    return _run("fred_release_dates", M.AUTHORITY_BACKSTOP, url, parse_fred_release_dates,
                fetch=fetch, now=now, terms=TERMS["fred_release_dates"])


def fetch_forexfactory(*, fetch: Callable = fetch_text, now: datetime = None) -> tuple:
    return _run("forexfactory", M.AUTHORITY_CONVENIENCE, FF_WEEK_URL, parse_forexfactory,
                fetch=fetch, now=now or M.utc_now(), terms=TERMS["forexfactory"])
