"""
REPLAY-4 — Counterfactual Decision Laboratory (2026-07-10).

Turns the replay engine from a trade scorer into a decision laboratory: re-run
an archived session with EXACTLY ONE authority's verdict counterfactually
flipped, and measure the alternate history against the baseline — funnel
deltas, first-divergence attribution, and SimBroker-scored outcomes for every
scan the override newly authorizes.

DOCTRINE:
  * ONE override per run (two flips destroy attribution — same discipline as
    one-flag ablations)
  * overrides are VERDICT flips at named seams; SAFETY CAPS ARE NOT VARIABLES —
    no override for risk dollars, max trades, daily loss, stops, sizing, FC-0B,
    or broker behavior exists in the registry, and the walker's forced
    no-execution env stands regardless
  * results are DESCRIPTIVE evidence (for governance, missions, and the health
    monitor) — the lab actuates nothing
  * an alternate history that scores WORSE is as valuable as one that scores
    better: the lab validates refusals too

Registry (v1):
  council_yes        what if the council had voted yes? (veto suppressed)
  adaptive_unblocked what if the adaptive soft-veto hadn't blocked?
  trigger_confirmed  what if we hadn't waited for confirmation? (expected to
                     score BADLY per the BOT-VS-MAURICE trial — a negative
                     control proving the lab detects harmful counterfactuals)
Deferred (documented, not silently absent): brain_direction_wins (forcing the
qualification direction is deep surgery), narrative_permits, size_plus_one
(sizing never runs in replay; the effect-ledger math covers size counterfactuals).

CLI: python -m replay_validation.counterfactual_lab --date 20260709 --override council_yes
"""
import json
import os
from datetime import datetime, timezone

from replay_validation.candle_archive import load_session
from replay_validation.metrics import score_trades, safety_invariants
from replay_validation.recorded_brain import _parse_ts
from replay_validation.replay_session import replay_session
from replay_validation.sim_broker import simulate_trade, stop_from_intent
from replay_validation.stage_trace import first_divergence


# ── override implementations (verdict flips at named seams) ────────────────────

def _ov_council_yes(stage, snapshot):
    if stage != "post_council":
        return
    veto = (snapshot.get("council") or {}).get("veto")
    if isinstance(veto, dict) and veto.get("veto_triggered"):
        veto["veto_triggered"] = False
        veto["veto_reason"] = ""
        veto["counterfactual_lab"] = "council_yes: veto suppressed"
        snapshot.setdefault("_lab_mutations", []).append("council_yes")


def _ov_adaptive_unblocked(stage, snapshot):
    if stage != "pre_decision":
        return
    ab = snapshot.get("adaptive_block")
    if isinstance(ab, dict) and ab.get("blocked"):
        ab["blocked"] = False
        ab["reason"] = []
        ab["counterfactual_lab"] = "adaptive_unblocked: soft veto lifted"
        snapshot.setdefault("_lab_mutations", []).append("adaptive_unblocked")


def _ov_trigger_confirmed(stage, snapshot):
    if stage != "pre_decision":
        return
    tb = snapshot.get("toolbox") or {}
    pref = tb.get("preferred_tool")
    for c in tb.get("tool_candidates") or []:
        if c.get("tool") != pref:
            continue
        tp = c.get("trigger_prep")
        pl = c.get("price_level") or {}
        if not isinstance(tp, dict) or pl.get("invalidated"):
            return
        if tp.get("raw_trigger_status") in ("confirmation_needed",
                                            "waiting_for_retest",
                                            "retest_in_progress"):
            tp["raw_trigger_status"] = "confirmed"
            tp["effective_trigger_status"] = "confirmed"
            tp["execution_ready"] = True
            tp["counterfactual_lab"] = "trigger_confirmed: confirmation waived"
            snapshot.setdefault("_lab_mutations", []).append("trigger_confirmed")
        return


OVERRIDES = {
    "council_yes": _ov_council_yes,
    "adaptive_unblocked": _ov_adaptive_unblocked,
    "trigger_confirmed": _ov_trigger_confirmed,
}

# Safety caps are NOT counterfactual variables — the registry must never grow
# an override whose name suggests otherwise (locked by test).
FORBIDDEN_OVERRIDE_TERMS = ("risk", "size", "loss", "stop", "broker",
                            "max_trades", "chase", "execution_enabled")


# ── outcome scoring of the alternate history ───────────────────────────────────

def _score_new_authorizations(date, symbol, baseline, altered):
    """SimBroker-score every scan the override NEWLY authorizes (market fill at
    the next bar per FC-0B, stop from the intent zone, live BE/TP management)."""
    try:
        tape = load_session(date, symbol)
    except FileNotFoundError:
        return {"trades": [], "note": "no candle archive"}
    trades, seen = [], set()
    base_by_i = {i: s for i, s in enumerate(baseline["scans"])}
    for i, scan in enumerate(altered["scans"]):
        t = scan["trace"]
        b = (base_by_i.get(i) or {}).get("trace") or {}
        if not t.get("would_authorize") or b.get("would_authorize"):
            continue
        direction = t.get("playbook_direction") or t.get("brain_direction")
        if direction not in ("bullish", "bearish"):
            continue
        # dedupe: one trade per (direction, minute-bucket) — consecutive
        # authorized scans of the same setup are one opportunity, not many
        key = (direction, str(t.get("timestamp"))[:16])
        if key in seen:
            continue
        seen.add(key)
        # stop from the scan's captured intent zone (invalidation first, zone
        # edge fallback); scans without a derivable stop are counted, not faked
        ez = scan.get("intent_zone") or {}
        stop = stop_from_intent(ez, direction,
                                invalidation_level=ez.get("invalidation_level"),
                                buffer=0.08) if ez else None
        if stop is None:
            trades.append({"timestamp": t.get("timestamp"),
                           "direction": direction, "skipped": "no_stop"})
            continue
        sim = simulate_trade(tape, t.get("timestamp"), direction, stop=stop,
                             target_r=2.0, breakeven_r=1.0)
        if sim:
            sim["timestamp"] = t.get("timestamp")
            trades.append(sim)
    scored = [t for t in trades if "r" in t]
    return {"new_authorized": len(seen),
            "trades": trades,
            "metrics": score_trades(scored),
            "safety": safety_invariants(scored)}


def run_lab(date: str, override: str, symbol: str = "QQQ",
            flags: dict = None, out_dir: str = None) -> dict:
    """ONE override, one date: baseline run + altered run + verdict."""
    if override not in OVERRIDES:
        raise ValueError(f"unknown override {override!r}; "
                         f"registry: {sorted(OVERRIDES)}")
    fn = OVERRIDES[override]
    mutated_scans = []

    def hook(stage, snapshot):
        before = len(snapshot.get("_lab_mutations", []) or [])
        fn(stage, snapshot)
        if len(snapshot.get("_lab_mutations", []) or []) > before:
            mutated_scans.append(snapshot.get("timestamp"))

    baseline = replay_session(date, symbol, flags=flags)
    altered = replay_session(date, symbol, flags=flags, post_stage_hook=hook)

    diffs, by_stage = 0, {}
    for a, b in zip(altered["scans"], baseline["scans"]):
        d = first_divergence(a["trace"], b["trace"])
        if d:
            diffs += 1
            by_stage[d["stage"]] = by_stage.get(d["stage"], 0) + 1

    outcomes = _score_new_authorizations(date, symbol, baseline, altered)

    report = {
        "lab": "counterfactual_decision_laboratory",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": date, "symbol": symbol, "override": override,
        "doctrine": "one override per run; safety caps are not variables",
        "scans": len(altered["scans"]),
        "scans_mutated": len(mutated_scans),
        "funnel_baseline": {k: baseline["summary"][k] for k in
                            ("qualified_scans", "intents", "confirmed_triggers",
                             "would_authorize")},
        "funnel_altered": {k: altered["summary"][k] for k in
                           ("qualified_scans", "intents", "confirmed_triggers",
                            "would_authorize")},
        "scans_diverged": diffs,
        "divergence_by_stage": by_stage,
        "alternate_history": outcomes,
        "authority": "descriptive_only",
    }
    out_dir = out_dir or os.path.join("data", "replay", "reports")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"lab_{override}_{date}_{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    report["saved"] = path
    return report


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Counterfactual Decision Laboratory")
    p.add_argument("--date", required=True)
    p.add_argument("--override", required=True, choices=sorted(OVERRIDES))
    p.add_argument("--symbol", default="QQQ")
    p.add_argument("--flags", nargs="*", default=[])
    a = p.parse_args()
    flags = dict(kv.split("=", 1) for kv in a.flags)
    r = run_lab(a.date, a.override, a.symbol, flags=flags or None)
    print(json.dumps({k: r[k] for k in
                      ("override", "date", "scans", "scans_mutated",
                       "funnel_baseline", "funnel_altered", "scans_diverged",
                       "divergence_by_stage", "saved")}, indent=1, default=str))
    ah = r["alternate_history"]
    print("alternate history:", json.dumps(
        {k: ah.get(k) for k in ("new_authorized", "metrics", "safety")},
        indent=1, default=str))
