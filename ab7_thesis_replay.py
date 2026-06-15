"""
Phase AB-7 — Thesis Lifecycle replay study.

Drives the persistent ThesisLifecycleEngine over the archived brain-call records
(data/ai_brain/*_QQQ.json) and measures how much scan-to-scan flicker the engine
removes vs the raw candidate stream. Pure offline measurement — touches no live
state. Validation gate for promoting AB-7 shadow -> enforce.

Usage:
  python ab7_thesis_replay.py            # all QQQ records, grouped by day
  python ab7_thesis_replay.py 20260615   # one day only
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from ai_brain.thesis_lifecycle import ThesisLifecycleEngine  # noqa: E402


def _candidate_from_record(rec: dict) -> dict:
    o = rec.get("parsed_output", {}) or {}
    d = (o.get("narrative_direction") or "neutral").lower()
    return {
        "owner": "ai_brain", "source": rec.get("source"),
        "direction": d,
        "forbidden_direction": o.get("forbidden_direction"),
        "opportunity": d in ("bullish", "bearish"),
        "opportunity_type": o.get("narrative_phase"),
        "playbook_family": o.get("recommended_playbook_family"),
        "tool_family": o.get("recommended_tool_family"),
        "confidence": int(o.get("phase_confidence") or 0),
        "dominant_reasoning": o.get("dominant_reasoning", ""),
        "brain_block": {"output": o},
    }


def _evidence_from_record(rec: dict) -> dict:
    ip = rec.get("input_payload", {}) or {}
    ev = {"snapshot_id": rec.get("timestamp")}
    mk = ip.get("market", {}) or {}
    if mk.get("current_price") is not None:
        ev["current_price"] = mk["current_price"]
    ps = ip.get("protected_swings", {}) or {}
    ev["protected_high_status"] = ps.get("protected_high_status")
    ev["protected_low_status"] = ps.get("protected_low_status")
    return ev


def _norm_pb(v):
    if isinstance(v, list):
        v = v[0] if v else None
    v = (v or "no_playbook")
    return "no_playbook" if v in ("", "none", None) else str(v).lower()


def _changes(seq):
    return sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])


def _drops_to_none(seq, none_vals):
    return sum(1 for i in range(1, len(seq))
               if seq[i] in none_vals and seq[i - 1] not in none_vals)


def replay_day(files):
    eng = ThesisLifecycleEngine(persist=False)
    raw_dir, raw_pb = [], []
    st_dir, st_pb = [], []
    actions = {}
    ids = set()
    for f in files:
        try:
            rec = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        cand = _candidate_from_record(rec)
        out = eng.update(cand, _evidence_from_record(rec), rec.get("timestamp"))
        raw_dir.append(cand["direction"])
        raw_pb.append(_norm_pb(cand["playbook_family"]) if cand["opportunity"] else "no_playbook")
        bt = eng.as_brain_thesis()
        st_dir.append((bt or {}).get("direction") or "neutral")
        st_pb.append(_norm_pb((bt or {}).get("playbook_family")) if bt and bt.get("opportunity") else "no_playbook")
        actions[out["action"]] = actions.get(out["action"], 0) + 1
        if out.get("thesis_id"):
            ids.add(out["thesis_id"])
    return {
        "scans": len(files),
        "raw_direction_changes": _changes(raw_dir),
        "stabilized_direction_changes": _changes(st_dir),
        "raw_no_playbook_drops": _drops_to_none(raw_pb, {"no_playbook"}),
        "stabilized_no_playbook_drops": _drops_to_none(st_pb, {"no_playbook"}),
        "distinct_theses": len(ids),
        "actions": actions,
    }


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else None
    pattern = os.path.join("data", "ai_brain",
                           f"{day}_*_QQQ.json" if day else "*_QQQ.json")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"No records match {pattern}")
        return

    by_day = {}
    for f in files:
        d = os.path.basename(f)[:8]
        by_day.setdefault(d, []).append(f)

    print("=" * 68)
    print("AB-7 THESIS LIFECYCLE REPLAY")
    print("=" * 68)
    tot_rdc = tot_sdc = tot_rpd = tot_spd = 0
    for d in sorted(by_day):
        r = replay_day(by_day[d])
        tot_rdc += r["raw_direction_changes"]; tot_sdc += r["stabilized_direction_changes"]
        tot_rpd += r["raw_no_playbook_drops"];  tot_spd += r["stabilized_no_playbook_drops"]
        print(f"\n{d}  ({r['scans']} scans, {r['distinct_theses']} distinct theses)")
        print(f"  direction changes : raw {r['raw_direction_changes']:>4}  ->  "
              f"stabilized {r['stabilized_direction_changes']:>4}")
        print(f"  no_playbook drops : raw {r['raw_no_playbook_drops']:>4}  ->  "
              f"stabilized {r['stabilized_no_playbook_drops']:>4}")
        print(f"  actions           : {r['actions']}")

    def pct(a, b):
        return f"{(1 - b / a) * 100:4.0f}% reduction" if a else "  n/a"
    print("\n" + "-" * 68)
    print("TOTAL")
    print(f"  direction changes : raw {tot_rdc:>4}  ->  stabilized {tot_sdc:>4}   {pct(tot_rdc, tot_sdc)}")
    print(f"  no_playbook drops : raw {tot_rpd:>4}  ->  stabilized {tot_spd:>4}   {pct(tot_rpd, tot_spd)}")
    print("=" * 68)


if __name__ == "__main__":
    main()
