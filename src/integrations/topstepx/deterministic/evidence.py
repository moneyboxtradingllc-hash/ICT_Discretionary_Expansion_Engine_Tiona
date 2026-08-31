"""Evidence recorder for the MNQ_DETERMINISTIC_SIM_WEEK era.

Append-only JSONL. Never blended with AI Brain / QQQ / smoke-test / replay
evidence — a distinct directory + era tag keep this lane's record separate.
"""
from __future__ import annotations

import json
import os
import time

from integrations.topstepx.deterministic import (
    EVIDENCE_ERA, MODE, AUTHOR, ACCOUNT, INSTRUMENT, MAX_RISK_DOLLARS, MAX_STOP_POINTS)

EVIDENCE_DIR = os.path.join("data", "integration", "topstepx", "deterministic", "evidence")


def _path() -> str:
    day = time.strftime("%Y%m%d")
    return os.path.join(EVIDENCE_DIR, f"{EVIDENCE_ERA}_{day}.jsonl")


def record_scan(session_id: str, scan_num: int, payload: dict) -> str:
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    rec = {
        "era": EVIDENCE_ERA, "mode": MODE, "author": AUTHOR,
        "account": ACCOUNT, "instrument": INSTRUMENT,
        "sizing": "risk-based", "max_risk_usd": MAX_RISK_DOLLARS, "max_stop_pts": MAX_STOP_POINTS,
        "session_id": session_id, "scan": scan_num, "at": time.time(),
        "at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **payload,
    }
    p = _path()
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return p
