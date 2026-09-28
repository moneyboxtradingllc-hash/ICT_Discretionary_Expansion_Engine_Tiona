"""NEWS-2 Phase 2 — the morning brief: FACTS, with a fenced-off interpretation slot.

The persisted object has two parts that never mix:

    factual          calendar view, headlines, market mood -- each with provenance
    interpretation   OPTIONAL human-readable text, labelled as interpretation,
                     carrying no authority. Empty in this pass: no model is
                     called to establish or summarise the facts.

The brief is never read by the scan, the Brain, the candidate producer or any
execution path. `authority` is "observe_only" and `brain_input` is False on the
object itself, so any future consumer has to defy an explicit marker to use it.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from news.factual import model as M
from news.factual.calendar import calendar_view

SCHEMA_BRIEF = "news2.morning_brief.v1"
STORE_DIR = os.path.join("data", "news", "brief")
INTERPRETATION_LABEL = ("INTERPRETATION -- human-readable only; not a fact, not "
                        "trading evidence, never Brain input")

#: Keys that would turn facts into a view. The factual block may not carry them.
FORBIDDEN_FACTUAL_KEYS = frozenset({"lean", "bias", "direction", "sentiment",
                                    "bullish", "bearish", "recommendation", "signal"})


def build_brief(*, now: datetime, calendar_state: dict, headlines: dict, mood: dict) -> dict:
    return {
        "schema_version": SCHEMA_BRIEF,
        "built_at": M.iso(now),
        "authority": "observe_only",
        "brain_input": False,
        "factual": {
            "calendar": calendar_view(calendar_state, now),
            "headlines": headlines,
            "market_mood": mood,
        },
        "interpretation": {
            "present": False,
            "label": INTERPRETATION_LABEL,
            "sovereign": False,
            "text": None,
            "model": None,
        },
    }


def factual_keys(obj, path="") -> list:
    """Every key path under `obj`, for the no-lean guarantee."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            out.append(p)
            out.extend(factual_keys(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(factual_keys(v, f"{path}[{i}]"))
    return out


def persist(brief: dict, store_dir: str = STORE_DIR) -> str:
    os.makedirs(store_dir, exist_ok=True)
    built = M.parse_instant(brief["built_at"]).astimezone(M.ET)
    path = os.path.join(store_dir, f"brief_{built:%Y%m%dT%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(brief, fh, indent=1, default=str)
    return path
