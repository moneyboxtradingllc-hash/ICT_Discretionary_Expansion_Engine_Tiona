"""
FAMILY-REPAIR LIVE REPLAY (2026-07-09) — measure BRAIN-FAMILY-REPAIR against the
sovereignty autopsy's missing-family scans.

The autopsy found 153 scans (41% of 372) where a healthy directional LLM read
carried playbook_family='none', blocking sovereignty. BRAIN-FAMILY-REPAIR
(23bfbec) shipped a prompt-salience fix + a soft repair turn, but every audited
record predates it — the repair has never fired on a real scan.

This tool re-fires the REAL LLM on the EXACT historical `input_payload` each gap
scan saw (higher fidelity than a walked reconstruction), through the CURRENT
prompt, and applies the shipped soft-repair logic verbatim:

  fresh call → normalize → gap?
    no gap            -> fixed_by_prompt      (salience effect alone)
    gap -> repair turn -> adoption guards (same direction as the fresh read,
          hard-validation pass, gap closed):
            adopted   -> fixed_by_repair
            dir flip  -> flip_rejected        (original kept — guard working)
            else      -> unfixed
  fresh call non-directional -> now_conflicted (the prompt's escape hatch:
        "not confident enough to name a playbook -> say conflicted")

Costs real API usage (gpt-4o-mini) and is non-deterministic — one pass is a
first measurement, not a distribution. Read-only against trading logic.

CLI: python -m replay_validation.family_repair_replay [--dates 20260708 20260709]
         [--limit N] [--out data/replay/reports]
"""
import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

from replay_validation.recorded_brain import load_brain_records

load_dotenv()


def gap_scans(date: str, symbol: str = "QQQ") -> list:
    """Historical scans where a healthy directional read had no family."""
    from ai_brain.ecu import _family_present
    from ai_brain.brain_validation import directional_family_gap
    out = []
    for ts, rec in load_brain_records(date, symbol):
        o = rec.get("parsed_output") or {}
        d = (o.get("narrative_direction") or "").lower()
        if rec.get("source") != "llm" or d not in ("bullish", "bearish"):
            continue
        if _family_present(o.get("recommended_playbook_family")) \
                or _family_present(o.get("recommended_tool_family")):
            continue
        gap, _ = directional_family_gap(o)
        if gap and rec.get("input_payload"):
            out.append((ts, rec))
    return out


def replay_one(rec: dict) -> dict:
    """One live measurement — mirrors narrative_brain's soft-repair block."""
    import ai_brain.narrative_brain as nb
    from ai_brain.brain_validation import (
        normalize_output, needs_repair, directional_family_gap,
    )
    hist = rec.get("parsed_output") or {}
    payload = rec.get("input_payload")
    result = {"timestamp": rec.get("timestamp"),
              "historical_direction": hist.get("narrative_direction"),
              "historical_family": hist.get("recommended_playbook_family"),
              "historical_confidence": hist.get("phase_confidence")}

    fresh = nb._call_llm(payload)
    if not fresh["ok"]:
        result.update(outcome="llm_error", detail=fresh["fallback_reason"])
        return result
    parsed, _ = normalize_output(fresh["parsed"])
    d = (parsed.get("narrative_direction") or "neutral").lower()
    result["fresh_direction"] = d
    result["fresh_family"] = parsed.get("recommended_playbook_family")
    result["fresh_confidence"] = parsed.get("phase_confidence")

    if d not in ("bullish", "bearish"):
        # the escape hatch worked: hedge became an honest conflicted/neutral
        result.update(outcome="now_conflicted")
        return result

    gap, errors = directional_family_gap(parsed)
    if not gap:
        result.update(outcome="fixed_by_prompt")
        return result

    rep = nb._call_llm(payload, repair={"previous": parsed, "errors": errors})
    if not rep["ok"]:
        result.update(outcome="repair_call_failed", detail=rep["fallback_reason"])
        return result
    cand, _ = normalize_output(rep["parsed"])
    still_hard, _ = needs_repair(cand)
    still_gap, _ = directional_family_gap(cand)
    same_dir = (cand.get("narrative_direction") == parsed.get("narrative_direction"))
    if not same_dir:
        result.update(outcome="flip_rejected",
                      detail=f"repair flipped {d} -> {cand.get('narrative_direction')}")
    elif not still_hard and not still_gap:
        result.update(outcome="fixed_by_repair",
                      repaired_family=cand.get("recommended_playbook_family"))
    else:
        result.update(outcome="unfixed",
                      detail=f"still_hard={still_hard} still_gap={still_gap}")
    return result


def run(dates=("20260708", "20260709"), symbol: str = "QQQ",
        limit: int = None, out_dir: str = None) -> dict:
    out_dir = out_dir or os.path.join("data", "replay", "reports")
    os.makedirs(out_dir, exist_ok=True)
    results, counts = [], {}
    for date in dates:
        scans = gap_scans(date, symbol)
        if limit:
            scans = scans[:limit]
        print(f"[{date}] gap scans to replay live: {len(scans)}")
        for i, (_ts, rec) in enumerate(scans, 1):
            r = replay_one(rec)
            r["date"] = date
            results.append(r)
            counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
            if i % 20 == 0:
                print(f"  [{date}] {i}/{len(scans)} … {counts}")
    fixed = counts.get("fixed_by_prompt", 0) + counts.get("fixed_by_repair", 0)
    total = len(results)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live_llm_on_historical_input_payload",
        "model": os.getenv("AI_BRAIN_MODEL", "gpt-4o-mini"),
        "note": "single pass; LLM non-deterministic",
        "gap_scans_replayed": total,
        "outcomes": counts,
        "fix_rate": round(fixed / total, 3) if total else None,
        "results": results,
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"family_repair_live_{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    print(f"\noutcomes: {counts}")
    print(f"fix rate: {fixed}/{total}")
    print(f"report saved: {path}")
    return report


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="BRAIN-FAMILY-REPAIR live replay")
    p.add_argument("--dates", nargs="*", default=["20260708", "20260709"])
    p.add_argument("--limit", type=int)
    p.add_argument("--out")
    a = p.parse_args()
    run(tuple(a.dates), limit=a.limit, out_dir=a.out)
