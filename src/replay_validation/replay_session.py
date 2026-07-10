"""
REPLAY-2 — chronological session walker (2026-07-09).

Replays an archived session through the CURRENT pipeline: scan_loop's exact
decision-critical stage order, minus network, printing, and broker. Statefulness
is preserved — the same persistent managers scan_loop threads (MarketMemory,
ThesisLifecycleEngine, ProtectedSwingTracker, Po3Stability, ExpansionStability,
SetupTracker, state-transition counters) are instantiated once per run and
advanced scan by scan. Half the shipped repairs live in that threaded state.

Scan ticks default to the day's recorded Brain-call timestamps (exact alignment
with the live session for calibration); falls back to a 60s grid over the
archived tape when no records exist.

SAFETY: the run env FORCES EXECUTION_ENABLED=false and ALLOW_PAPER_ORDERS=false,
disables shadow/retrieval/news side-effects, and sandboxes every writable data
dir. Replay authorizes on paper only via gate.would_authorize_if_enabled; it can
never place an order. Declared caveats (news off, retrieval off, empty adaptive
history, fresh memory) ship inside the run manifest.

CLI:
  python -m replay_validation.replay_session --date 20260708
      [--symbol QQQ] [--flags K=V ...] [--calibrate] [--out data/replay/runs]
"""
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from replay_validation.candle_archive import load_session
from replay_validation.recorded_brain import RecordedBrain, brain_replay, _parse_ts
from replay_validation.stage_trace import (
    build_stage_trace, trace_from_stored, first_divergence,
    PERCEPTION_FIELDS, STORED_TRIMMED_FIELDS, BRAIN_FIELDS, CALIBRATION_FIELDS,
    _SCHEMA, _FIELD_STAGE, STAGE_OWNER,
)

_LOOKBACK_DEFAULT = 300   # scan_loop: SCAN_LOOKBACK_BARS default


# Baseline replay environment. Safety keys are HARD (always forced); the
# caller's flags manifest may override behavior flags but never the safety keys.
_SAFETY_ENV = {
    "EXECUTION_ENABLED":   "false",
    "ALLOW_PAPER_ORDERS":  "false",
    "AI_SHADOW_ENABLED":   "false",
    "AI_RETRIEVAL_ENABLED": "false",
    "NEWS_LAYER_ENABLED":  "false",
}

# Brain modes (REPLAY-2 LIVE addition, 2026-07-09):
#   recorded      — RecordedBrain serves persisted outputs (deterministic, free)
#   live          — the REAL LLM is called on the reconstructed inputs
#                   (non-deterministic, costs API usage; for Brain-side repairs)
#   deterministic — LLM off, mechanical fallback brain only
_BRAIN_MODE_ENV = {
    "recorded":      {"AI_BRAIN_LLM": "false"},   # substitution handles it
    "live":          {"AI_BRAIN_LLM": "true"},
    "deterministic": {"AI_BRAIN_LLM": "false"},
}
_BASE_ENV = {
    "AI_BRAIN_ENABLED":    "true",
    "BRAIN_ECU_MODE":      "true",
    "AI_MODE":             "internal",
}
_SANDBOX_DIR_KEYS = (
    "LIVE_SNAPSHOTS_DIR", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR",
    "REPLAY_CANDLES_DIR_UNUSED_GUARD",  # never redirect the archive itself
)


@contextmanager
def _replay_env(flags: dict, sandbox: str):
    """Apply base + caller flags + forced safety keys + sandboxed data dirs."""
    env = dict(_BASE_ENV)
    env.update(flags or {})
    env.update(_SAFETY_ENV)             # safety keys always win
    env["LIVE_SNAPSHOTS_DIR"] = os.path.join(sandbox, "live_snapshots")
    env["AI_BRAIN_DIR"] = os.path.join(sandbox, "ai_brain")
    env["AI_RETRIEVAL_DIR"] = os.path.join(sandbox, "ai_retrieval")
    for d in ("live_snapshots", "ai_brain", "ai_retrieval"):
        os.makedirs(os.path.join(sandbox, d), exist_ok=True)
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _default_ticks(date: str, symbol: str, candles: list, brain: RecordedBrain) -> list:
    """Recorded Brain-call timestamps (exact live alignment) or a 60s grid."""
    if brain.records:
        return [ts for ts, _rec in brain.records]
    ticks, last = [], None
    for c in candles:
        ts = _parse_ts(c.get("timestamp"))
        if ts and (last is None or (ts - last) >= timedelta(seconds=60)):
            ticks.append(ts)
            last = ts
    return ticks


def replay_session(date: str, symbol: str = "QQQ", flags: dict = None,
                   ticks: list = None, lookback: int = _LOOKBACK_DEFAULT,
                   sandbox: str = None, max_scans: int = None,
                   brain: str = "recorded", post_stage_hook=None) -> dict:
    """Replay one archived session through the current pipeline.
    brain: recorded (default, deterministic) | live (real LLM calls) |
    deterministic (mechanical fallback only).
    post_stage_hook (REPLAY-4 Counterfactual Decision Laboratory): optional
    callable(stage_name, snapshot) invoked at the named seams — "post_build",
    "post_council", "pre_decision", "post_gate" — allowing a counterfactual
    run to flip ONE authority's verdict in-place. Replay-side only; never used
    by the trading pipeline. Hook exceptions are swallowed (a broken hook must
    not masquerade as organism behavior — the scan errors instead).
    Returns {"manifest", "scans": [{timestamp, trace}], "summary"}."""
    if brain not in _BRAIN_MODE_ENV:
        raise ValueError(f"unknown brain mode: {brain!r}")
    candles = load_session(date, symbol)   # raises if never archived
    prev_date = None
    try:  # prior session extends the lookback window across the open
        prev = (datetime.strptime(date, "%Y%m%d") - timedelta(days=1))
        for back in range(1, 6):
            d = (datetime.strptime(date, "%Y%m%d") - timedelta(days=back)).strftime("%Y%m%d")
            try:
                candles = load_session(d, symbol) + candles
                prev_date = d
                break
            except FileNotFoundError:
                continue
    except Exception:  # noqa: BLE001
        pass

    parsed = [( _parse_ts(c.get("timestamp")), c) for c in candles]
    parsed = [(ts, c) for ts, c in parsed if ts is not None]
    parsed.sort(key=lambda p: p[0])

    # RecordedBrain is always constructed — its record timestamps are the tick
    # grid even in live/deterministic modes; substitution happens only in
    # recorded mode.
    rec_brain = RecordedBrain(date, symbol)
    tick_list = ticks or _default_ticks(date, symbol,
                                        [c for _ts, c in parsed], rec_brain)

    own_sandbox = sandbox is None
    sandbox = sandbox or tempfile.mkdtemp(prefix=f"replay_{date}_")

    manifest = {
        "date": date, "symbol": symbol, "flags": dict(flags or {}),
        "forced_safety": dict(_SAFETY_ENV),
        "brain_mode": brain, "brain_records": len(rec_brain.records),
        "counterfactual_hook": bool(post_stage_hook),
        "candles": len(parsed), "prev_session_loaded": prev_date,
        "lookback": lookback, "scans_planned": len(tick_list),
        "caveats": ["news_off", "retrieval_off", "shadow_off",
                    "fresh_memory", "empty_adaptive_history", "no_execution"]
                   + (["live_llm_nondeterministic"] if brain == "live" else []),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    from contextlib import nullcontext
    mode_flags = dict(flags or {})
    mode_flags.update(_BRAIN_MODE_ENV[brain])
    brain_ctx = brain_replay(rec_brain) if brain == "recorded" else nullcontext()
    scans, errors = [], []
    with _replay_env(mode_flags, sandbox), brain_ctx:
        # ── persistent per-run state (mirrors scan_loop init) ────────────────
        from state.market_memory import MarketMemory
        from ai_brain.thesis_lifecycle import ThesisLifecycleEngine
        from narrative_authority.protected_swings import ProtectedSwingTracker
        from structure.po3_alignment_manager import Po3StabilityManager
        from volatility.expansion_stability import ExpansionStabilityManager
        from setup_lifecycle.setup_tracker import SetupTracker
        from market_data.snapshot_builder import build_snapshot
        from data_feed.timeframe_builder import build_timeframes
        from state_transitions.transition_engine import analyze_transition
        from shared_context.shared_market_context import build_shared_market_context
        from shared_context.council import run_council
        from decision_authority.decision_engine import make_decision
        from execution_gate.execution_gate import evaluate_gate
        from market_commander.market_commander import build_market_commander_matrix
        from trade_intent.intent_builder import build_intent
        from adaptive_learning.adaptive_live_authority import consume_adaptive_overlays

        memory = MarketMemory(max_snapshots=20)
        thesis_engine = ThesisLifecycleEngine(symbol=symbol)
        swing_tracker = ProtectedSwingTracker()
        po3_stability = Po3StabilityManager()
        expansion_stability = ExpansionStabilityManager()
        setup_tracker = SetupTracker()
        previous_snapshot, previous_qual_state, bars_in_state = None, None, 0

        for tick in tick_list:
            if max_scans and len(scans) >= max_scans:   # cap EXECUTED scans,
                break                                    # not head-of-tick-list
            window = [c for ts, c in parsed if ts <= tick][-lookback:]
            if len(window) < 20:
                continue
            try:
                raw_data = build_timeframes(window)
                snapshot = build_snapshot(
                    raw_data,
                    memory=memory,
                    thesis_engine=thesis_engine,
                    symbol=symbol,
                    swing_tracker=swing_tracker,
                    po3_stability=po3_stability,
                    expansion_stability=expansion_stability,
                )

                def _hook(stage):
                    if post_stage_hook is not None:
                        post_stage_hook(stage, snapshot)

                _hook("post_build")
                # ── scan_loop's post-snapshot decision-critical order ────────
                cur_qual = (snapshot.get("qualification", {}).get("status")
                            or "no_trade").lower()
                bars_in_state = bars_in_state + 1 if cur_qual == previous_qual_state else 1
                snapshot["state_transition"] = analyze_transition(
                    snapshot, previous_snapshot, bars_in_state)
                previous_snapshot, previous_qual_state = snapshot, cur_qual

                snapshot["setup_lifecycle"] = setup_tracker.update(snapshot, symbol)
                snapshot["shared_context"] = build_shared_market_context(snapshot, symbol)
                snapshot["council"] = run_council(snapshot["shared_context"])
                _hook("post_council")

                _canonical = (snapshot.get("candidate_thesis") or {}).get("brain_block")
                if _canonical is not None:
                    snapshot["ai_brain"] = _canonical

                consume_adaptive_overlays(snapshot)
                _hook("pre_decision")
                snapshot["decision_authority"] = make_decision(snapshot)
                snapshot["execution_gate"] = evaluate_gate(snapshot)
                snapshot["market_commander"] = build_market_commander_matrix(snapshot)
                snapshot["trade_intent"] = build_intent(snapshot, symbol)
                _hook("post_gate")

                # intent-zone capture (REPLAY-3/4 outcome scoring input)
                _ez = dict((snapshot.get("trade_intent") or {})
                           .get("entry_zone") or {})
                for _c in (snapshot.get("toolbox") or {}).get("tool_candidates") or []:
                    if _c.get("tool") == (snapshot.get("toolbox") or {}).get("preferred_tool"):
                        _ez["invalidation_level"] = (
                            (_c.get("price_level") or {}).get("invalidation_level"))
                        break
                scans.append({"timestamp": snapshot.get("timestamp"),
                              "trace": build_stage_trace(snapshot),
                              "intent_zone": _ez or None})
            except Exception as exc:  # noqa: BLE001 — one bad scan must not kill the run
                errors.append({"tick": tick.isoformat(), "error": repr(exc)})

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    summary = _summarize(scans, rec_brain if brain == "recorded" else None, errors)
    if own_sandbox:
        manifest["sandbox"] = sandbox
    return {"manifest": manifest, "scans": scans, "summary": summary}


def _summarize(scans: list, brain: "RecordedBrain | None", errors: list) -> dict:
    traces = [s["trace"] for s in scans]
    return {
        "scans": len(scans),
        "errors": len(errors),
        "error_detail": errors[:5],
        "brain_served": brain.served if brain else None,   # None in live/deterministic
        "brain_misses": brain.misses if brain else None,
        "sovereign_scans": sum(1 for t in traces if t.get("brain_sovereign")),
        "qualified_scans": sum(1 for t in traces
                               if t.get("qual_status") in ("candidate", "qualified", "elite")),
        "intents": sum(1 for t in traces if t.get("intent_created")),
        "confirmed_triggers": sum(1 for t in traces
                                  if t.get("trigger_status") == "confirmed"),
        "would_authorize": sum(1 for t in traces if t.get("would_authorize")),
    }


def calibrate(result: dict, date: str, symbol: str = "QQQ",
              snapshots_dir: str = None) -> dict:
    """Compare a replay run against the STORED live snapshots (ground truth).
    Perception fields are excluded (stored snapshots persist decisions, not raw
    inputs). Returns per-stage divergence counts + samples."""
    sdir = snapshots_dir or os.path.join("data", "live_snapshots")
    stored = {}
    if os.path.isdir(sdir):
        for name in sorted(os.listdir(sdir)):
            if name.startswith(date) and name.endswith(f"_{symbol}.json"):
                try:
                    tr = trace_from_stored(os.path.join(sdir, name))
                    ts = _parse_ts(tr.get("timestamp"))
                    if ts:
                        stored[ts] = tr
                except Exception:  # noqa: BLE001
                    continue
    matched, diverged, by_stage, samples = 0, 0, {}, []
    field_match = {f: 0 for f in CALIBRATION_FIELDS}
    # Compare DECISION-level fields only (CALIBRATION_FIELDS): the store trims
    # perception/ai_context/trigger_prep, and reason/blocker TEXT evolves across
    # revisions — comparing it would count wording changes as behavior.
    skip = tuple(f for f in _FIELD_STAGE if f not in CALIBRATION_FIELDS)
    for scan in result["scans"]:
        ts = _parse_ts(scan["timestamp"])
        if ts is None or not stored:
            continue
        best = min(stored, key=lambda k: abs((k - ts).total_seconds()))
        if abs((best - ts).total_seconds()) > 90:
            continue
        matched += 1
        for f in CALIBRATION_FIELDS:
            if scan["trace"].get(f) == stored[best].get(f):
                field_match[f] += 1
        div = first_divergence(scan["trace"], stored[best], skip_fields=skip)
        if div:
            diverged += 1
            by_stage[div["stage"]] = by_stage.get(div["stage"], 0) + 1
            if len(samples) < 10:
                samples.append({"timestamp": scan["timestamp"], **div})
    rates = ({f: round(field_match[f] / matched, 3) for f in CALIBRATION_FIELDS}
             if matched else {})
    return {"stored_snapshots": len(stored), "matched": matched,
            "identical": matched - diverged, "diverged": diverged,
            "divergence_by_stage": by_stage,
            "field_match_rates": rates, "samples": samples}


def _main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="REPLAY-2 session walker")
    p.add_argument("--date", required=True)
    p.add_argument("--symbol", default="QQQ")
    p.add_argument("--flags", nargs="*", default=[], help="K=V behavior flags")
    p.add_argument("--brain", default="recorded",
                   choices=("recorded", "live", "deterministic"))
    p.add_argument("--max-scans", type=int)
    p.add_argument("--calibrate", action="store_true")
    p.add_argument("--out", default=os.path.join("data", "replay", "runs"))
    args = p.parse_args()

    flags = dict(kv.split("=", 1) for kv in args.flags)
    result = replay_session(args.date, args.symbol, flags=flags,
                            max_scans=args.max_scans, brain=args.brain)
    print(json.dumps(result["summary"], indent=2))
    if args.calibrate:
        cal = calibrate(result, args.date, args.symbol)
        result["calibration"] = cal
        print("calibration:", json.dumps(
            {k: v for k, v in cal.items() if k != "samples"}, indent=2))
        for s in cal["samples"][:5]:
            print(f"  divergence @{s['timestamp']}: {s['stage']}.{s['field']} "
                  f"replay={s['a']!r} live={s['b']!r}")
    run_id = f"{args.date}_{args.symbol}_{datetime.now().strftime('%H%M%S')}"
    out_dir = os.path.join(args.out, run_id)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, default=str)
    print(f"run saved: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
