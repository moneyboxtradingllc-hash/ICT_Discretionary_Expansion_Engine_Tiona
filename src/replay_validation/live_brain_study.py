"""
LIVE BRAIN STUDY (Mission 2, 2026-07-09) — full-organism live-LLM replays.

Replays archived sessions through the CURRENT pipeline with the REAL Brain
(walker brain="live"), N runs per (session, BRAIN_FAMILY_REPAIR mode) because
LLM output is non-deterministic; compares against the RecordedBrain baseline.

  single run : python -m replay_validation.live_brain_study run
                   --date 20260709 --repair on --run 3
  baseline   : python -m replay_validation.live_brain_study run
                   --date 20260709 --repair recorded --run 0
  aggregate  : python -m replay_validation.live_brain_study aggregate

Isolation per run: fresh sandbox dirs, forced no-execution safety env,
identical archived candles + tick grid (RecordedBrain timestamps) in every
mode — so scans align 1:1 across recorded/live runs.

Measurement only. No prompt changes, no trading-logic changes.
"""
import json
import os
import statistics
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

STUDY_DIR = os.path.join("data", "replay", "runs", "live_study")

# The day's historical mechanical manifest — IDENTICAL across all runs of a
# session; only BRAIN_FAMILY_REPAIR differs between the B and C arms.
BASE = {
    "DIRECTION_CONFLICT_VETO": "true",
    "COUNCIL_AUTHORITY": "enforce",
    "COUNCIL_VETO_MIN_NO_VOTES": "2",
    "COUNCIL_VETO_MIN_CONFIDENCE": "70",
    "RULE_GOVERNANCE_MODE": "enforce",
    "PROMOTED_RULES": "R-001",
    "NARRATIVE_AUTHORITY": "enforce",
    "QUALIFICATION_THESIS_FLOOR": "true",
    "EXPANSION_STABILITY_MODE": "on",
    "EXPANSION_STABILITY_CONFIRM": "3",
    "SETUP_NO_PLAYBOOK_GRACE": "2",
    "VOLATILITY_AUTHORITY_MODE": "observe_only",
    "REGIME_AUTHORITY_MODE": "observe_only",
    "MARKET_COMMANDER_AUTHORITY_MODE": "enforce",
    "EXPANSION_CONTINUATION_TRIGGER": "on",
    "MECHANICAL_JUDGES_MODE": "telemetry_only",
}

_NON_FAMILIES = {"", "none", "unknown", "confirmation_required", "n/a", "null"}

# BRAIN-MODEL-TRIAL (2026-07-10) — the CURRENT organism stack (launcher parity
# as of the trial date), so a model arm measures the MODEL and nothing else.
CURRENT_STACK = dict(BASE, **{
    "THESIS_LIFECYCLE_MODE": "enforce",
    "BRAIN_KEEP_SHALLOW_REASONING": "true",
    "BRAIN_JSON_MODE": "on",
    "BRAIN_PHASE_SYNONYM_TOLERANCE": "on",
    "BRAIN_FAMILY_REPAIR": "on",
    "BRAIN_INVALIDATION_REPAIR": "on",
    "BRAIN_ACCURACY_CONTEXT": "on",
    # INTENT-SCORE-AUDIT (2026-07-10) + R-001-AUDIT (2026-07-11) demotions —
    # BASE keeps the historical values; the CURRENT stack mirrors the launcher
    "INTENT_SCORE_MODE": "observe_only",
    "RULE_GOVERNANCE_MODE": "shadow",
    # BRAIN-AUTHORSHIP-CLOSURE (2026-07-13) — launcher parity
    "BRAIN_AUTHORSHIP_REQUIRED": "on",
})


def _fam_missing(v) -> bool:
    items = v if isinstance(v, list) else [v]
    return all(str(i).lower().strip() in _NON_FAMILIES
               for i in items if i is not None) or not items


def run_metrics(traces: list) -> dict:
    n = len(traces) or 1
    directional = [t for t in traces
                   if t.get("brain_direction") in ("bullish", "bearish")]
    return {
        "scans": len(traces),
        "sovereign": sum(1 for t in traces if t.get("brain_sovereign")),
        "directional": len(directional),
        "pb_none_of_directional": sum(
            1 for t in directional if _fam_missing(t.get("brain_playbook_family"))),
        "tool_none_of_directional": sum(
            1 for t in directional if _fam_missing(t.get("brain_tool_family"))),
        "family_repair_attempted": sum(
            1 for t in traces if t.get("family_repair_attempted")),
        "family_repair_fixed": sum(
            1 for t in traces if t.get("family_repair_fixed")),
        "qualified": sum(1 for t in traces
                         if t.get("qual_status") in ("candidate", "qualified", "elite")),
        "intents": sum(1 for t in traces if t.get("intent_created")),
        "confirmed_triggers": sum(1 for t in traces
                                  if t.get("trigger_status") == "confirmed"),
        "would_authorize": sum(1 for t in traces if t.get("would_authorize")),
    }


class _RateLimitedLLM:
    """Study-side 429 backoff (replay infra ONLY — trading logic untouched).

    Wave 1 (2026-07-09) proved parallel replays hit the org TPM limit: 1,249
    RateLimitError 429s contaminated 78-96% of scans with deterministic
    fallbacks. _call_llm has max_retries=0 by design (a live scan must never
    stall the loop); a REPLAY has no such constraint, so we retry 429s with
    backoff instead of polluting the measurement."""

    def __init__(self, inner, max_retries: int = 5, base_sleep: float = 15.0):
        self._inner = inner
        self.max_retries = max_retries
        self.base_sleep = base_sleep
        self.retries = 0

    def __call__(self, brain_input, repair=None):
        import time
        out = self._inner(brain_input, repair=repair)
        attempt = 0
        while (not out["ok"]
               and "RateLimitError" in str(out.get("fallback_reason") or "")
               and attempt < self.max_retries):
            attempt += 1
            self.retries += 1
            time.sleep(self.base_sleep * attempt)
            out = self._inner(brain_input, repair=repair)
        return out


def do_run(date: str, repair: str, run_idx: int, model: str = None) -> str:
    """One replay run; writes traces + metrics to the study dir.
    repair: recorded | off | on — or model:<name> (BRAIN-MODEL-TRIAL arm:
    CURRENT organism stack, live brain, AI_BRAIN_MODEL=<name>)."""
    from replay_validation.replay_session import replay_session
    os.makedirs(STUDY_DIR, exist_ok=True)
    if model or repair.startswith("model:"):
        model = model or repair.split(":", 1)[1]
        repair = f"model_{model}"
        brain = "live"
        flags = dict(CURRENT_STACK, AI_BRAIN_MODEL=model)
    elif repair == "recorded":
        brain, flags = "recorded", dict(BASE)
    else:
        brain = "live"
        flags = dict(BASE, BRAIN_FAMILY_REPAIR=("on" if repair == "on" else "off"))
    import ai_brain.narrative_brain as nb
    limiter = _RateLimitedLLM(nb._call_llm) if brain == "live" else None
    original = nb._call_llm
    if limiter:
        nb._call_llm = limiter
    try:
        result = replay_session(date, flags=flags, brain=brain)
    finally:
        nb._call_llm = original
    traces = [s["trace"] for s in result["scans"]]
    rec = {
        "date": date, "repair": repair, "run": run_idx,
        "brain_mode": brain,
        "metrics": run_metrics(traces),
        "errors": result["summary"]["errors"],
        "rate_limit_retries": limiter.retries if limiter else 0,
        "llm_source_scans": sum(
            1 for s in result["scans"]
            if s["trace"].get("brain_source") == "llm"),
        "scans": result["scans"],
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    path = os.path.join(STUDY_DIR, f"{date}_{repair}_{run_idx}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, default=str)
    print(f"[study] {date} repair={repair} run={run_idx}: "
          f"{json.dumps(rec['metrics'])} errors={rec['errors']}")
    return path


# ── aggregation ────────────────────────────────────────────────────────────────

def _load_runs():
    runs = {}
    if not os.path.isdir(STUDY_DIR):
        return runs
    for name in sorted(os.listdir(STUDY_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(STUDY_DIR, name), encoding="utf-8") as fh:
            r = json.load(fh)
        runs.setdefault((r["date"], r["repair"]), []).append(r)
    return runs


def _agg(vals):
    if not vals:
        return None
    return {"mean": round(statistics.mean(vals), 1),
            "min": min(vals), "max": max(vals),
            "stdev": round(statistics.stdev(vals), 1) if len(vals) > 1 else 0.0}


def _score_forward(date: str, timestamp: str, direction: str,
                   horizon_min: int = 45) -> "dict | None":
    """Outcome-score a divergent would-authorize scan on the archived forward
    candles: directional move over the horizon (favor/adverse, in points)."""
    from replay_validation.candle_archive import load_session
    from replay_validation.recorded_brain import _parse_ts
    try:
        candles = load_session(date)
    except FileNotFoundError:
        return None
    ts = _parse_ts(timestamp)
    fwd = [c for c in candles
           if (_parse_ts(c.get("timestamp")) or ts) > ts][:horizon_min]
    if not fwd or ts is None:
        return None
    entry = float(fwd[0]["open"])
    if direction in ("bullish", "long"):
        fav = max(float(c["high"]) for c in fwd) - entry
        adv = entry - min(float(c["low"]) for c in fwd)
    else:
        fav = entry - min(float(c["low"]) for c in fwd)
        adv = max(float(c["high"]) for c in fwd) - entry
    return {"entry": round(entry, 2), "mfe_pts": round(fav, 2),
            "mae_pts": round(adv, 2),
            "better": fav > adv}


def aggregate(out_dir: str = None) -> dict:
    from replay_validation.stage_trace import first_divergence
    out_dir = out_dir or os.path.join("data", "replay", "reports")
    os.makedirs(out_dir, exist_ok=True)
    runs = _load_runs()
    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "sessions": {}, "divergence_vs_recorded": {},
              "new_authorize_outcomes": []}

    for date in sorted({d for d, _r in runs}):
        sess = {}
        for repair in ("recorded", "off", "on"):
            batch = runs.get((date, repair), [])
            if not batch:
                continue
            keys = batch[0]["metrics"].keys()
            sess[repair] = {
                "runs": len(batch),
                "per_run": [b["metrics"] for b in batch],
                "agg": {k: _agg([b["metrics"][k] for b in batch]) for k in keys},
                "errors": sum(b["errors"] for b in batch),
            }
        report["sessions"][date] = sess

        # per-scan divergence: each live run vs the recorded baseline
        base = runs.get((date, "recorded"), [])
        if base:
            base_scans = base[0]["scans"]
            for repair in ("off", "on"):
                stages, brain_diffs, scans_div = {}, 0, []
                for b in runs.get((date, repair), []):
                    for i, scan in enumerate(b["scans"][:len(base_scans)]):
                        div = first_divergence(scan["trace"],
                                               base_scans[i]["trace"])
                        if div:
                            stages[div["stage"]] = stages.get(div["stage"], 0) + 1
                            if div["stage"] == "brain":
                                brain_diffs += 1
                        # NEW would-authorize (live true, recorded false)
                        if scan["trace"].get("would_authorize") and \
                                not base_scans[i]["trace"].get("would_authorize"):
                            scans_div.append(scan)
                report["divergence_vs_recorded"][f"{date}_{repair}"] = {
                    "first_divergence_by_stage": stages,
                    "brain_stage_divergences": brain_diffs,
                }
                for scan in scans_div[:20]:
                    sc = _score_forward(date, scan["trace"].get("timestamp"),
                                        scan["trace"].get("brain_direction") or "")
                    report["new_authorize_outcomes"].append({
                        "date": date, "repair": repair,
                        "timestamp": scan["trace"].get("timestamp"),
                        "direction": scan["trace"].get("brain_direction"),
                        "playbook": scan["trace"].get("playbook_selected"),
                        "forward_score": sc,
                    })

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"live_brain_study_{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    print(f"aggregate saved: {path}")
    return report


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Live Brain study")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--date", required=True)
    r.add_argument("--repair", default="on")
    r.add_argument("--model", help="BRAIN-MODEL-TRIAL arm: AI_BRAIN_MODEL name")
    r.add_argument("--run", type=int, default=0)
    sub.add_parser("aggregate")
    a = p.parse_args()
    if a.cmd == "run":
        do_run(a.date, a.repair, a.run, model=a.model)
    else:
        aggregate()
