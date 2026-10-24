"""Operator view: the Brain's authored market read beside participation permission.

    python3 -I tools/narrative_read_report.py <persisted brain-call dir> [--json]

Reads persisted Brain call records (`<YYYYMMDD_HHMMSS>_<SYM>.json`) offline. For
every call it shows, as three separate columns:

    AUTHORED     what the Brain read (record `authored_market_read`; for a
                 record written before NARRATIVE-FIRST-1, the original
                 `llm_raw_response`, labelled LEGACY_RAW_RESPONSE)
    PERMITTED    the guarded participation output (`parsed_output`)
    REFUSAL      the hold/guard explanation (`narrative_authority_guard`)

It never reconstructs an authored read from the guarded output, and it grants
nothing: the authored column is OBSERVATIONAL_ONLY.
"""
import json
import os
import re
import sys

CALL = re.compile(r"^\d{8}_\d{6}_[A-Z]+\.json$")
STORY_CHARS = 240


def _authored(rec):
    read = rec.get("authored_market_read")
    if isinstance(read, dict):
        if read.get("status") == "AVAILABLE":
            return {"basis": "authored_market_read", "status": "AVAILABLE",
                    "direction": read.get("narrative_direction"),
                    "action": read.get("authored_action"),
                    "story": read.get("market_story")}
        return {"basis": "authored_market_read", "status": "UNKNOWN",
                "reason": read.get("reason")}
    raw = rec.get("llm_raw_response")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {"basis": "LEGACY_RAW_RESPONSE", "status": "UNKNOWN",
                    "reason": "raw_response_not_json"}
        if isinstance(parsed, dict):
            return {"basis": "LEGACY_RAW_RESPONSE", "status": "AVAILABLE",
                    "direction": parsed.get("narrative_direction"),
                    "action": parsed.get("current_action"),
                    "story": parsed.get("market_story")}
    return {"basis": None, "status": "UNKNOWN", "reason": "no_authored_read_recorded"}


def rows(directory):
    out = []
    for name in sorted(os.listdir(directory)):
        if not CALL.match(name):
            continue
        try:
            rec = json.load(open(os.path.join(directory, name), encoding="utf-8"))
        except (OSError, ValueError):
            out.append({"file": name, "error": "unreadable"})
            continue
        permitted = rec.get("parsed_output") or {}
        guard = rec.get("narrative_authority_guard") or {}
        out.append({
            "file": name, "cutoff": rec.get("timestamp"),
            "llm_model": rec.get("llm_model"),
            "provider_latency_seconds": rec.get("provider_latency_seconds"),
            "authored": _authored(rec),
            "permitted": {"direction": permitted.get("narrative_direction"),
                          "action": permitted.get("current_action"),
                          "story": permitted.get("market_story")},
            "refusal": {"status": guard.get("status"),
                        "reason": guard.get("reason"),
                        "control_state": guard.get("control_state")},
        })
    return out


def render(items):
    lines = []
    for r in items:
        if "error" in r:
            lines.append(f"{r['file']}: {r['error']}")
            continue
        a, p, g = r["authored"], r["permitted"], r["refusal"]
        lines.append(f"== {r['cutoff']}  ({r['file']}, model {r['llm_model']})")
        if a["status"] == "AVAILABLE":
            lines.append(f"  AUTHORED  [{a['basis']}] {a['direction']} / {a['action']}: "
                         f"{str(a['story'] or '')[:STORY_CHARS]}")
        else:
            lines.append(f"  AUTHORED  UNKNOWN ({a.get('reason')})")
        lines.append(f"  PERMITTED {p['direction']} / {p['action']}: "
                     f"{str(p['story'] or '')[:STORY_CHARS]}")
        lines.append(f"  REFUSAL   {g['status']} ({g['reason']}; control {g['control_state']})")
    return "\n".join(lines)


def main():
    items = rows(sys.argv[1])
    print(json.dumps(items, indent=1, default=str) if "--json" in sys.argv[2:] else render(items))


if __name__ == "__main__":
    main()
