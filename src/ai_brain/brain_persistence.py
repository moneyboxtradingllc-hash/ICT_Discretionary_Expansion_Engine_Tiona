"""
Phase AB-1 — Brain call persistence (no more discarded reasoning).

Every brain call writes: full input payload, raw response, parsed response,
fields consumed vs ignored, and the source (llm|deterministic|degraded).
Outcome/lesson attachment is a later AB phase (needs trade linkage). Writes
one JSON file per call to data/ai_brain/. Never raises.
"""
import json
import os
from datetime import datetime

import pytz

_EASTERN = pytz.timezone("America/New_York")


def _dir() -> str:
    return os.getenv("AI_BRAIN_DIR", os.path.join("data", "ai_brain"))


def persist_brain_call(symbol: str, record: dict) -> "str | None":
    try:
        d = _dir()
        os.makedirs(d, exist_ok=True)
        ts = datetime.now(_EASTERN).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(d, f"{ts}_{symbol}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=1, default=str)
        return path
    except Exception:  # noqa: BLE001
        return None
