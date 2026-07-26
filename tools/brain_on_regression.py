"""Brain-on before/after regression harness.

The deterministic-lane check could not answer this. `build_mnq_snapshot` raises
if `openai` is even imported, and the deterministic author's mech_gate omits
`brain_authorship` entirely â€” so that comparison ran with the brain off by
construction and says nothing about the brain-on path.

It matters because the changed modules are SHARED. Only facts_provider.py and
loop.py are deterministic-lane specific; snapshot_builder, expansion_detector,
po3_engine, regime_features/classifier and price_levels are consumed by
scan_loop.py, main.py and replay_session.py too. brain_input reads po3 phases,
po3_alignment, manipulation/distribution direction, market_regime,
expansion_state and the structure swings â€” all of which moved.

Two interaction surfaces are untested and this is built to expose them:

  1. The brain's THESIS itself, because its evidence changed. PO3 was welded to
     `accumulation` on every scan before LEG-SCOPE; now it moves.
  2. selected_playbook. Under ECU the brain's playbook_family becomes the
     selected playbook (playbook_classifier.py:458-464), and regime_permissions
     keys on selected_playbook + regime_label with _REVERSAL_ONLY_REGIMES
     blocking non-reversal families. Brain-chosen playbook now meets a regime
     label this branch changed.

COST: every cutoff issues real brain calls against your API key, once per code
version. Twelve cutoffs is twenty-four calls. --dry-run makes no calls and prints
exactly what would run.

Usage
-----
  # no API calls â€” verify wiring and see the plan
  python tools/brain_on_regression.py --dry-run

  # capture one side (run once per code version, then diff)
  python tools/brain_on_regression.py --label BEFORE --src /path/to/baseline/src \
      --out before_brain.json --cuts 12:45,13:10,13:30

  python tools/brain_on_regression.py --label AFTER --out after_brain.json \
      --cuts 12:45,13:10,13:30

  # compare
  python tools/brain_on_regression.py --diff before_brain.json after_brain.json
"""
import argparse
import json
import os
import sys
from datetime import datetime

DEFAULT_CUTS = ["10:15", "12:05", "12:20", "12:45", "13:10", "13:30", "13:35", "14:00"]
JOURNAL = ("C:/Users/jesus/ICT_Discretionary_Expansion_Engine/data/integration/"
           "ninjatrader/ipc_journal.jsonl")

# Fields compared. Chosen to cover the brain's own output AND the gate surface it
# feeds, since a thesis that changes but never reaches the gate is not a risk.
THESIS_FIELDS = ("direction", "forbidden_direction", "opportunity_type",
                 "playbook_family", "tool_family", "confidence")
GATE_FIELDS = ("trigger_requirement_met", "narrative_permits_trade",
               "commander_permits_trade", "council_permits_trade",
               "regime_permission_allowed", "no_promoted_rule_block",
               "brain_authorship_ok")


def load_bars():
    sz = os.path.getsize(JOURNAL)
    last = None
    with open(JOURNAL, "rb") as fh:
        fh.seek(max(0, sz - 40_000_000))
        fh.readline()
        for line in fh:
            try:
                env = json.loads(line)["env"]
                if env.get("message_type") == "HISTORICAL_BARS_RESPONSE":
                    last = env
            except Exception:
                pass
    if last is None:
        raise SystemExit("no HISTORICAL_BARS_RESPONSE found in the journal")
    return [{"timestamp": b["t"], "open": b["o"], "high": b["h"], "low": b["l"],
             "close": b["c"], "volume": b.get("v"), "instrument": "MNQ SEP26"}
            for b in last["payload"]["bars"]]


def capture(cuts, day):
    """Build a brain-on snapshot per cutoff and extract the comparison surface."""
    from data_feed.timeframe_builder import build_timeframes
    from market_data.snapshot_builder import build_snapshot
    from execution_gate.execution_gate import evaluate_gate

    raw = load_bars()
    results = {}
    for cut in cuts:
        cutoff = datetime.fromisoformat(f"{day}T{cut}:00-04:00")
        bars = [b for b in raw
                if datetime.fromisoformat(b["timestamp"]) <= cutoff]
        if len(bars) < 400:
            results[cut] = {"skipped": f"only {len(bars)} bars"}
            continue
        snap = build_snapshot(build_timeframes(bars), symbol="MNQ SEP26")
        gate = evaluate_gate(snap)
        thesis = snap.get("brain_thesis") or {}
        po3 = snap.get("po3") or {}
        regime = snap.get("market_regime") or {}
        results[cut] = {
            "thesis": {k: thesis.get(k) for k in THESIS_FIELDS},
            "brain_present": bool(thesis),
            "selected_playbook": (snap.get("playbook") or {}).get("selected_playbook"),
            "regime_label": regime.get("regime_label"),
            "trend_score": regime.get("trend_score"),
            "po3_5m": (po3.get("5m") or {}).get("phase"),
            "po3_15m": (po3.get("15m") or {}).get("phase"),
            "po3_alignment": po3.get("alignment"),
            "gate": {k: bool(gate.get(k)) for k in GATE_FIELDS},
        }
    return results


def diff(before_path, after_path):
    b = json.load(open(before_path))["results"]
    a = json.load(open(after_path))["results"]
    cuts = sorted(set(b) | set(a))

    def section(title):
        print(f"\n=== {title} ===")

    section("thesis / playbook")
    print(f"{'cut':<8}{'playbook BEFORE -> AFTER':<44}{'brain direction B -> A':<28}")
    for c in cuts:
        B, A = b.get(c, {}), a.get(c, {})
        pb = f"{B.get('selected_playbook')} -> {A.get('selected_playbook')}"
        db = f"{(B.get('thesis') or {}).get('direction')} -> " \
             f"{(A.get('thesis') or {}).get('direction')}"
        print(f"{c:<8}{pb:<44}{db:<28}")

    section("gate permission differences")
    found = False
    for c in cuts:
        gb = (b.get(c) or {}).get("gate", {})
        ga = (a.get(c) or {}).get("gate", {})
        d = {k: (gb.get(k), ga.get(k)) for k in set(gb) | set(ga)
             if gb.get(k) != ga.get(k)}
        if d:
            found = True
            print(f"  {c}: {d}")
    if not found:
        print("  none â€” every gate permission identical at every cutoff")

    section("brain thesis differences")
    found = False
    for c in cuts:
        tb = (b.get(c) or {}).get("thesis", {}) or {}
        ta = (a.get(c) or {}).get("thesis", {}) or {}
        d = {k: (tb.get(k), ta.get(k)) for k in THESIS_FIELDS
             if tb.get(k) != ta.get(k)}
        if d:
            found = True
            print(f"  {c}: {d}")
    if not found:
        print("  none â€” brain authored the same thesis at every cutoff")

    section("upstream evidence the brain reads")
    for c in cuts:
        B, A = b.get(c, {}), a.get(c, {})
        if (B.get("po3_5m"), B.get("regime_label")) != \
           (A.get("po3_5m"), A.get("regime_label")):
            print(f"  {c}: po3_5m {B.get('po3_5m')} -> {A.get('po3_5m')}, "
                  f"regime {B.get('regime_label')} -> {A.get('regime_label')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="RUN")
    ap.add_argument("--src", default=None,
                    help="src/ to import from (a baseline worktree for BEFORE)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--cuts", default=",".join(DEFAULT_CUTS))
    ap.add_argument("--day", default="2026-07-24")
    ap.add_argument("--dry-run", action="store_true",
                    help="make no API calls; print the plan and verify wiring")
    ap.add_argument("--no-llm", action="store_true",
                    help="brain layer + ECU on but AI_BRAIN_LLM off - no API "
                         "spend, still exercises playbook authorship and the gate")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()

    if args.diff:
        diff(*args.diff)
        return

    cuts = [c.strip() for c in args.cuts.split(",") if c.strip()]

    # Three independent switches, set explicitly so a run can never depend on
    # ambient shell state:
    #   AI_BRAIN_ENABLED  the brain layer itself
    #   BRAIN_ECU_MODE    the ECU pre-pass â€” this is what lets the brain author
    #                     selected_playbook, the surface that meets regime
    #   AI_BRAIN_LLM      the actual external model call. OFF costs nothing and
    #                     still exercises every wiring path below the LLM.
    os.environ["AI_BRAIN_ENABLED"] = "true"
    os.environ["BRAIN_ECU_MODE"] = "true"
    os.environ["AI_BRAIN_LLM"] = "false" if args.no_llm else "true"

    if args.src:
        sys.path.insert(0, args.src)
    else:
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "src"))

    if args.dry_run:
        os.environ["AI_BRAIN_ENABLED"] = "false"
        os.environ["BRAIN_ECU_MODE"] = "false"
        os.environ["AI_BRAIN_LLM"] = "false"
        calls = "0 (LLM off)" if args.no_llm else f"~{len(cuts)}"
        print("DRY RUN - no API calls will be made\n")
        print(f"  label      : {args.label}")
        print(f"  src        : {args.src or '(this repo)'}")
        print(f"  day        : {args.day}")
        print(f"  cutoffs    : {len(cuts)}  {cuts}")
        print(f"  API calls  : {calls} for this side")
        print(f"  would set  : AI_BRAIN_ENABLED=true BRAIN_ECU_MODE=true "
              f"AI_BRAIN_LLM={'false' if args.no_llm else 'true'}")
        from ai_brain.ecu import ecu_enabled
        from ai_brain import narrative_brain as nb
        print("\n  wiring check (all forced false during a dry run):")
        print(f"    ecu_enabled()     -> {ecu_enabled()}   [BRAIN_ECU_MODE]")
        print(f"    nb.enabled()      -> {nb.enabled()}   [AI_BRAIN_ENABLED]")
        print(f"    nb._llm_enabled() -> {nb._llm_enabled()}   [AI_BRAIN_LLM]")
        bars = load_bars()
        print(f"  bars loaded: {len(bars)} "
              f"({bars[0]['timestamp'][:16]} .. {bars[-1]['timestamp'][:16]})")
        print("\n  Nothing was sent. Re-run without --dry-run to capture.")
        return

    print(f"[{args.label}] brain ON â€” capturing {len(cuts)} cutoffs "
          f"API calls: {chr(48) if args.no_llm else chr(126)}", file=sys.stderr)
    results = capture(cuts, args.day)
    payload = {"label": args.label, "day": args.day, "results": results}
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(payload, fh, indent=1, default=str)
        print(f"[{args.label}] wrote {args.out}", file=sys.stderr)
    else:
        print(json.dumps(payload, indent=1, default=str))


if __name__ == "__main__":
    main()
