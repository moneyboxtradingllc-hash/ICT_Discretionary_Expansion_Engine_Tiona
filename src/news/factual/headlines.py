"""NEWS-2 Phase 2 — unscheduled headline FACTS. Observe-only; never raises.

Sources in this pass:
  * Federal Reserve press-release RSS (official, public domain)
  * Finnhub general market news (free key, FINNHUB_API_KEY), when configured

Each item keeps the source's `published_at` apart from our `retrieved_at`, and
names affected tickers ONLY when the source lists them explicitly. There is no
sentiment, no relevance score and no lean: those are interpretations.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET_XML
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

from news.factual import model as M
from news.factual.http import fetch_text, redact

FED_PRESS_RSS = "https://www.federalreserve.gov/feeds/press_all.xml"
FINNHUB_NEWS = "https://finnhub.io/api/v1/news"

TERMS = {
    "fed_press_rss": "U.S. government feed (public domain).",
    "finnhub_news": "Free-tier key (FINNHUB_API_KEY); 60 calls/min; Finnhub terms apply.",
}


def _item(*, headline, source, published_at, retrieved_at, url, source_name,
          related=None, summary=None) -> dict:
    return {"headline": headline, "source": source, "source_name": source_name,
            "published_at": published_at, "retrieved_at": retrieved_at,
            "age_minutes": (round(M.age_seconds(published_at, retrieved_at) / 60.0, 1)
                            if M.age_seconds(published_at, retrieved_at) is not None else None),
            "scheduled": False, "url": url,
            "related_explicit": related or [], "summary": summary}


def parse_fed_rss(text: str, *, retrieved_at: str) -> list:
    root = ET_XML.fromstring(text)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        pub = it.findtext("pubDate")
        try:
            published = parsedate_to_datetime(pub).astimezone(timezone.utc) if pub else None
        except (TypeError, ValueError):
            published = None
        if not title:
            continue
        items.append(_item(headline=title, source="Federal Reserve",
                           published_at=M.iso(published), retrieved_at=retrieved_at,
                           url=(it.findtext("link") or "").strip() or None,
                           source_name="fed_press_rss"))
    return items


def parse_finnhub(text: str, *, retrieved_at: str) -> list:
    rows = json.loads(text)
    if not isinstance(rows, list):
        raise ValueError("expected a JSON array")
    items = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("headline"):
            continue
        try:
            published = datetime.fromtimestamp(int(r.get("datetime")), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            published = None
        related = [t.strip() for t in str(r.get("related") or "").split(",") if t.strip()]
        items.append(_item(headline=str(r["headline"]).strip(), source=r.get("source"),
                           published_at=M.iso(published), retrieved_at=retrieved_at,
                           url=r.get("url"), source_name="finnhub_news",
                           related=related, summary=(r.get("summary") or None)))
    return items


def _collect(name, url, parser, *, fetch, now, terms):
    retrieved_at = M.iso(now)
    status = {"source_name": name, "reference": redact(url), "fetched_at": retrieved_at,
              "terms_note": terms, "status": None, "reason": None, "record_count": 0}
    res = fetch(url)
    if not res.get("ok"):
        status.update(status=M.SOURCE_FAILED, reason=res.get("error"))
        return status, []
    try:
        items = parser(res.get("text") or "", retrieved_at=retrieved_at)
    except Exception as exc:  # noqa: BLE001
        status.update(status=M.SOURCE_PARSE_FAILED, reason=f"{type(exc).__name__}: {exc}")
        return status, []
    status.update(status=M.SOURCE_OK if items else M.SOURCE_EMPTY,
                  record_count=len(items))
    return status, items


def collect_headlines(*, finnhub_key: Optional[str], fetch: Callable = fetch_text,
                      now: datetime = None, lookback_hours: float = 16.0) -> dict:
    now = now or M.utc_now()
    results = [_collect("fed_press_rss", FED_PRESS_RSS, parse_fed_rss,
                        fetch=fetch, now=now, terms=TERMS["fed_press_rss"])]
    if finnhub_key:
        results.append(_collect("finnhub_news",
                                f"{FINNHUB_NEWS}?category=general&token={finnhub_key}",
                                parse_finnhub, fetch=fetch, now=now,
                                terms=TERMS["finnhub_news"]))
    else:
        results.append(({"source_name": "finnhub_news", "status": M.SOURCE_UNAVAILABLE,
                         "reason": "FINNHUB_API_KEY not set", "reference": FINNHUB_NEWS,
                         "fetched_at": M.iso(now), "terms_note": TERMS["finnhub_news"],
                         "record_count": 0}, []))
    cutoff = now - timedelta(hours=lookback_hours)
    items = []
    for _, its in results:
        for it in its:
            t = M.parse_instant(it.get("published_at"))
            if t is None or t >= cutoff:        # undated items are kept, never dropped silently
                items.append(it)
    items.sort(key=lambda i: i.get("published_at") or "", reverse=True)
    ok = any(s["status"] == M.SOURCE_OK for s, _ in results)
    return {"data_state": M.KNOWN if ok else M.UNKNOWN,
            "reason": None if ok else "no headline source returned data",
            "lookback_hours": lookback_hours, "sources": [s for s, _ in results],
            "items": items}


def observed_reaction(published_at: str, bars: list, *, horizons=(5, 15)) -> dict:
    """MNQ move from the bar containing publication to +N minutes. Measured only."""
    t0 = M.parse_instant(published_at)
    if t0 is None:
        return {"measurable": False, "reason": "no publication time"}
    series = {}
    for b in bars or []:
        t = M.parse_instant((b or {}).get("timestamp"))
        if t is not None:
            try:
                series[t] = float(b["close"])
            except (KeyError, TypeError, ValueError):
                pass
    start = t0.replace(second=0, microsecond=0)
    if start not in series:
        return {"measurable": False, "reason": "no bar at publication minute"}
    out = {"measurable": True, "anchor_bar": M.iso(start), "anchor_close": series[start]}
    for h in horizons:
        end = start + timedelta(minutes=h)
        out[f"move_{h}m"] = (round(series[end] - series[start], 2) if end in series else None)
    return out
