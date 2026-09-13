"""Pure, non-gating execution observability calculations."""
from __future__ import annotations

from datetime import datetime, timezone


def parse_timestamp(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def elapsed_seconds(start, end):
    start_dt, end_dt = parse_timestamp(start), parse_timestamp(end)
    if start_dt is None or end_dt is None:
        return None
    seconds = (end_dt - start_dt).total_seconds()
    return round(seconds, 6) if seconds >= 0 else None


def invalidation_age(*, evidence_timestamp, observed_at):
    seconds = elapsed_seconds(evidence_timestamp, observed_at)
    return {"seconds": seconds,
            "status": "KNOWN" if seconds is not None else "UNKNOWN",
            "evidence_timestamp": evidence_timestamp,
            "observed_at": observed_at,
            "unknown_reason": None if seconds is not None else
            "missing_or_malformed_timestamp"}
