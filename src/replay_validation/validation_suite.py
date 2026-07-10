"""
REPLAY VALIDATION SUITE (2026-07-09) — measured flag-ablation validation of the
repair campaign. For each repair: replay the affected session with the repair's
flag OFF vs ON (all other flags at the day's historical manifest), diff the
per-scan stage traces, and report ONLY measured results.

Determinism gate passed 2026-07-09 (two full 0708 runs byte-identical), so an
OFF/ON diff is attributable to the flipped flag alone.

CLI: python -m replay_validation.validation_suite [--out data/replay/reports]
"""
import json
import os
from datetime import datetime, timezone

from replay_validation.replay_session import replay_session
from replay_validation.stage_trace import first_divergence, PERCEPTION_FIELDS

# Historical launcher manifest per day (base for every ablation on that day).
BASE_0708 = {
    "DIRECTION_CONFLICT_VETO": "true",
    "COUNCIL_AUTHORITY": "enforce",
    "COUNCIL_VETO_MIN_NO_VOTES": "2",
    "COUNCIL_VETO_MIN_CONFIDENCE": "70",
    "RULE_GOVERNANCE_MODE": "enforce",
    "PROMOTED_RULES": "R-001",
    "NARRATIVE_AUTHORITY": "enforce",
    "QUALIFICATION_THESIS_FLOOR": "true",
    "EXPANSION_STABILITY_MODE": "on",
    "SETUP_NO_PLAYBOOK_GRACE": "2",
    "VOLATILITY_AUTHORITY_MODE": "observe_only",
}
BASE_0709 = dict(BASE_0708, **{
    "EXPANSION_STABILITY_CONFIRM": "3",
    "REGIME_AUTHORITY_MODE": "observe_only",
    "MARKET_COMMANDER_AUTHORITY_MODE": "enforce",
    "EXPANSION_CONTINUATION_TRIGGER": "on",
    "MECHANICAL_JUDGES_MODE": "telemetry_only",
})

# (repair, date, base, flag, off_value, on_value)
ABLATIONS = [
    ("PERCEPTION-1 expansion hysteresis", "20260708", BASE_0708,
     "EXPANSION_STABILITY_MODE", "off", "on"),
    ("PERCEPTION-2 confirm window 3", "20260708", BASE_0708,
     "EXPANSION_STABILITY_CONFIRM", "2", "3"),
    ("SETUP-PERSIST no_playbook grace", "20260708", BASE_0708,
     "SETUP_NO_PLAYBOOK_GRACE", "0", "2"),
    ("VOL-AUTH-1 volatility observe_only", "20260708", BASE_0708,
     "VOLATILITY_AUTHORITY_MODE", "enforce", "observe_only"),
    ("REGIME-DEMOTE regime observe_only", "20260709", BASE_0709,
     "REGIME_AUTHORITY_MODE", "enforce", "observe_only"),
    ("MC-ENFORCE commander authority", "20260709", BASE_0709,
     "MARKET_COMMANDER_AUTHORITY_MODE", "observe_only", "enforce"),
    ("JUDGE-FREEZE + AI_CONTEXT-AUTHORITY (joint flag)", "20260709", BASE_0709,
     "MECHANICAL_JUDGES_MODE", "active", "telemetry_only"),
    ("RETEST-DOCTRINE expansion trigger", "20260709", BASE_0709,
     "EXPANSION_CONTINUATION_TRIGGER", "off", "on"),
]

# Not ablatable in recorded replay — reported explicitly, never inferred.
NOT_MEASURABLE = [
    ("BRAIN-FAMILY-REPAIR", "requires LIVE brain mode: the soft repair loop is "
     "an extra LLM round-trip; RecordedBrain serves historical outputs and "
     "cannot exercise it"),
    ("THESIS-PERSIST", "observability-only repair (snapshot persistence); it "
     "changes no decision path, so there is no behavioral ablation to measure"),
]


def _funnel(summary: dict) -> dict:
    return {k: summary.get(k) for k in
            ("scans", "sovereign_scans", "qualified_scans", "intents",
             "would_authorize", "errors")}


def compare_runs(off_run: dict, on_run: dict) -> dict:
    """Scan-aligned diff (ticks are identical and deterministic per day)."""
    diffs, by_stage, samples = 0, {}, []
    pairs = list(zip(off_run["scans"], on_run["scans"]))
    for off_scan, on_scan in pairs:
        div = first_divergence(off_scan["trace"], on_scan["trace"])
        if div:
            diffs += 1
            by_stage[div["stage"]] = by_stage.get(div["stage"], 0) + 1
            if len(samples) < 8:
                samples.append({"timestamp": on_scan["timestamp"], **div})
    return {"scans_compared": len(pairs), "scans_diverged": diffs,
            "first_divergence_by_stage": by_stage, "samples": samples}


def run_suite(out_dir: str = None) -> dict:
    out_dir = out_dir or os.path.join("data", "replay", "reports")
    os.makedirs(out_dir, exist_ok=True)
    cache = {}   # (date, flags-key) -> run

    def _run(date, flags):
        key = (date, tuple(sorted(flags.items())))
        if key not in cache:
            cache[key] = replay_session(date, flags=flags)
        return cache[key]

    results = []
    for name, date, base, flag, off_v, on_v in ABLATIONS:
        off_flags = dict(base, **{flag: off_v})
        on_flags = dict(base, **{flag: on_v})
        off_run = _run(date, off_flags)
        on_run = _run(date, on_flags)
        results.append({
            "repair": name, "date": date, "flag": flag,
            "off_value": off_v, "on_value": on_v,
            "funnel_off": _funnel(off_run["summary"]),
            "funnel_on": _funnel(on_run["summary"]),
            "diff": compare_runs(off_run, on_run),
        })
        print(f"[suite] {name}: diverged "
              f"{results[-1]['diff']['scans_diverged']}/"
              f"{results[-1]['diff']['scans_compared']} scans")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "determinism_gate": "PASS (2026-07-09, byte-identical double run)",
        "brain_mode": "recorded",
        "caveats": ["no execution (SimBroker = REPLAY-3): broker intents / "
                    "executed / win-loss / expectancy / MFE / MAE are measured "
                    "as 0 via would_authorize; funnel is the measured surface",
                    "news/retrieval/shadow off; fresh memory; no account state"],
        "ablations": results,
        "not_measurable": [{"repair": r, "reason": why}
                           for r, why in NOT_MEASURABLE],
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"validation_suite_{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    print(f"report saved: {path}")
    return report


if __name__ == "__main__":
    run_suite()
