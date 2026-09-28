"""NEWS-2 normalized objects, data states and freshness. Pure; no I/O.

Two clocks are kept apart everywhere, because conflating them is how delayed
data passes for live:

    observed / published   when the SOURCE says the fact was true or released
    fetched / retrieved    when WE read it

A daily VIX close observed on Friday and fetched on Monday morning is three
days old, not "current", whatever time we fetched it.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

SCHEMA_EVENT = "news2.scheduled_event.v1"
SCHEMA_CALENDAR = "news2.calendar_state.v1"
SCHEMA_SOURCE = "news2.source_status.v1"

ET = ZoneInfo("America/New_York")

# ── data states ──────────────────────────────────────────────────────────────
KNOWN = "known"
STALE = "stale"
UNKNOWN = "unknown"
CONFLICT = "conflict"
DATA_STATES = (KNOWN, STALE, UNKNOWN, CONFLICT)

# ── source fetch outcomes ────────────────────────────────────────────────────
SOURCE_OK = "ok"
SOURCE_FAILED = "failed"            # transport/HTTP error
SOURCE_UNAVAILABLE = "unavailable"  # not configured (e.g. no API key)
SOURCE_PARSE_FAILED = "parse_failed"
SOURCE_EMPTY = "empty"              # answered, but nothing usable in it
SOURCE_STATES = (SOURCE_OK, SOURCE_FAILED, SOURCE_UNAVAILABLE,
                 SOURCE_PARSE_FAILED, SOURCE_EMPTY)

# ── authority of a source for SCHEDULED events, highest first ───────────────
AUTHORITY_OFFICIAL = "official"          # the releasing agency's own schedule
AUTHORITY_BACKSTOP = "backstop"          # FRED release metadata (date only)
AUTHORITY_CONVENIENCE = "convenience"    # ForexFactory: cross-check only
AUTHORITY_RANK = {AUTHORITY_OFFICIAL: 0, AUTHORITY_BACKSTOP: 1,
                  AUTHORITY_CONVENIENCE: 2}

# ── how the release TIME was established ─────────────────────────────────────
TIME_SOURCE_EXPLICIT = "source_explicit"      # the source states the time
TIME_AGENCY_CONVENTION = "agency_convention"  # the agency's standing release
                                              # time applied to a sourced DATE

# ── categories (the owner's list, 2026-09-27) ───────────────────────────────
CPI = "CPI"
PPI = "PPI"
NFP = "NFP"
PCE = "PCE"
GDP = "GDP"
FOMC_DECISION = "FOMC_DECISION"
FOMC_MINUTES = "FOMC_MINUTES"
FED_CHAIR = "FED_CHAIR"
ISM = "ISM"
RETAIL_SALES = "RETAIL_SALES"
JOBLESS_CLAIMS = "JOBLESS_CLAIMS"
CATEGORIES = (CPI, PPI, NFP, PCE, GDP, FOMC_DECISION, FOMC_MINUTES, FED_CHAIR,
              ISM, RETAIL_SALES, JOBLESS_CLAIMS)

#: OUR analysis grouping for event-window MEASUREMENT only. It is deliberately
#: not called `impact_class`: impact_class is carried only when a source states
#: it explicitly. This tier assigns no authority and blocks nothing.
ANALYSIS_TIER1 = frozenset({CPI, PPI, NFP, PCE, GDP, FOMC_DECISION, FED_CHAIR})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_instant(value) -> Optional[datetime]:
    """An AWARE UTC datetime, or None. A naive value is refused, not guessed."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def age_seconds(then, now) -> Optional[float]:
    a, b = parse_instant(then), parse_instant(now)
    if a is None or b is None:
        return None
    return round((b - a).total_seconds(), 1)


def freshness(fetched_at, now, max_age_seconds: float) -> str:
    """KNOWN when fresh, STALE when older than allowed, UNKNOWN when unprovable."""
    age = age_seconds(fetched_at, now)
    if age is None:
        return UNKNOWN
    return KNOWN if age <= max_age_seconds else STALE


def event_id(category: str, scheduled_at_utc: str) -> str:
    """Stable identity of ONE scheduled occurrence, independent of source."""
    raw = f"{category}|{scheduled_at_utc}"
    return "evt_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class SourceStatus:
    source_name: str
    status: str                      # one of SOURCE_STATES
    authority: str
    fetched_at: Optional[str] = None
    reason: Optional[str] = None
    reference: Optional[str] = None
    record_count: int = 0
    terms_note: Optional[str] = None
    schema_version: str = SCHEMA_SOURCE

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SourceRecord:
    """What ONE source said about ONE occurrence. Never merged away."""
    source_name: str
    authority: str
    reference: Optional[str]
    fetched_at: Optional[str]
    scheduled_at: Optional[str]            # UTC ISO
    time_basis: str                        # TIME_SOURCE_EXPLICIT | TIME_AGENCY_CONVENTION
    source_title: Optional[str] = None
    source_published_at: Optional[str] = None
    impact_class: Optional[str] = None     # only when the source states it
    actual: Optional[str] = None
    consensus: Optional[str] = None
    previous: Optional[str] = None
    convention_note: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScheduledEvent:
    """One normalized scheduled occurrence, with every source that named it."""
    event_id: str
    name: str
    category: str
    scheduled_at: Optional[str]          # UTC ISO of the PRIMARY source
    timezone: str                        # the release's local zone
    scheduled_local: Optional[str]       # scheduled_at rendered in `timezone`
    primary_source: str
    primary_authority: str
    time_basis: str
    data_state: str                      # KNOWN | STALE | UNKNOWN | CONFLICT
    cross_check_status: str              # confirmed | conflict | single_source
    impact_class: Optional[str] = None
    impact_class_source: Optional[str] = None
    actual: Optional[str] = None
    consensus: Optional[str] = None
    previous: Optional[str] = None
    values_source: Optional[str] = None
    sources: list = field(default_factory=list)   # list[SourceRecord dict]
    conflicts: list = field(default_factory=list)
    schema_version: str = SCHEMA_EVENT

    def to_dict(self) -> dict:
        return asdict(self)


def local_render(scheduled_at_utc: Optional[str], zone: str = "America/New_York") -> Optional[str]:
    dt = parse_instant(scheduled_at_utc)
    return dt.astimezone(ZoneInfo(zone)).isoformat() if dt else None
