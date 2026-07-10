"""
ADAPT-LOOP-2 — Adaptive Effect Ledger: the adaptive layer grades itself
(2026-07-09).

The organism examination found the SECOND-ORDER loop missing: when the adaptive
layer acts (soft-block, confidence-lowering, size-reduction), nothing measured
whether THAT action helped. The suppression engine covers full blocks; the
partial actuations (ADAPTIVE-6 confidence, ADAPTIVE-7 size) were unaccounted.

This module is the pipeline-side RECORDER (telemetry only, zero authority):
each scan where an adaptive actuation fired AND a trade intent existed, one
idempotent action record is appended to the per-symbol ledger:

    data/performance/<SYM>/adaptive_effect_open.jsonl

The OUTCOME half lives in replay_validation.adaptive_effect_resolver (the
replay engine owns outcome scoring via SimBroker); it writes
adaptive_effect_resolved.jsonl + adaptive_effect_metrics.json, which this
module reads back for the learning layer. The pipeline never imports the
replay engine — evidence flows through data files (suppression pattern).

Gated by ADAPTIVE_EFFECT_LEDGER (default off = byte-identical legacy; the FC
launcher opts in). Fail-safe: never raises, never blocks a scan.
"""
import json
import os
from datetime import datetime, timezone

from deployment.data_paths import resolve

_OPEN_FILE = "adaptive_effect_open.jsonl"
_RESOLVED_FILE = "adaptive_effect_resolved.jsonl"
_METRICS_FILE = "adaptive_effect_metrics.json"


def ledger_enabled() -> bool:
    return os.getenv("ADAPTIVE_EFFECT_LEDGER", "off").lower().strip() == "on"


def _symbol_dir(symbol: str, base_dir: "str | None" = None) -> str:
    root = base_dir or resolve("PERFORMANCE_TABLES_DIR", "data", "performance",
                               anchored=True)
    d = os.path.join(root, str(symbol).upper())
    os.makedirs(d, exist_ok=True)
    return d


def _paths(symbol: str, base_dir=None):
    d = _symbol_dir(symbol, base_dir)
    return (os.path.join(d, _OPEN_FILE), os.path.join(d, _RESOLVED_FILE),
            os.path.join(d, _METRICS_FILE))


def _actions_from_snapshot(snapshot: dict) -> list:
    """Fired adaptive actuations this scan (type + detail)."""
    out = []
    alc = snapshot.get("adaptive_live_consumption") or {}
    ab = snapshot.get("adaptive_block") or {}
    if ab.get("blocked"):
        out.append({"action_type": "soft_block",
                    "detail": {"reason": ab.get("reason")}})
    if alc.get("adaptive_confidence_consumed"):
        out.append({"action_type": "confidence_lower",
                    "detail": {"original": alc.get("original_live_confidence"),
                               "final": alc.get("final_live_confidence")}})
    if alc.get("adaptive_size_consumed"):
        out.append({"action_type": "size_reduce",
                    "detail": {"original_qty": alc.get("original_live_qty"),
                               "final_qty": alc.get("final_live_qty")}})
    return out


def record_adaptive_actions(snapshot: dict, symbol: str,
                            base_dir: "str | None" = None) -> dict:
    """Scan-time recorder. Appends one open record per fired action when a
    directional trade intent gives the action a measurable context. Idempotent
    per (scan timestamp, action_type). Never raises."""
    result = {"enabled": ledger_enabled(), "recorded": 0, "actions": []}
    try:
        if not ledger_enabled():
            return result
        actions = _actions_from_snapshot(snapshot or {})
        if not actions:
            return result
        ti = (snapshot or {}).get("trade_intent") or {}
        ez = ti.get("entry_zone") or {}
        if not ti.get("intent_created") or ez.get("zone_low") is None:
            result["skip_reason"] = "no measurable intent context"
            return result

        ts = str((snapshot or {}).get("timestamp") or
                 datetime.now(timezone.utc).isoformat())
        open_path, _res, _met = _paths(symbol, base_dir)
        existing = set()
        if os.path.exists(open_path):
            with open(open_path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        existing.add(json.loads(line).get("action_id"))
                    except json.JSONDecodeError:
                        continue

        pref = None
        for c in (snapshot.get("toolbox") or {}).get("tool_candidates") or []:
            if c.get("tool") == (snapshot.get("toolbox") or {}).get("preferred_tool"):
                pref = c
                break
        inval = ((pref or {}).get("price_level") or {}).get("invalidation_level")

        with open(open_path, "a", encoding="utf-8") as fh:
            for a in actions:
                action_id = f"AE_{symbol}_{ts}_{a['action_type']}"
                if action_id in existing:
                    continue
                rec = {
                    "action_id": action_id,
                    "timestamp": ts,
                    "symbol": symbol,
                    "action_type": a["action_type"],
                    "detail": a["detail"],
                    # counterfactual context (SimBroker inputs)
                    "direction": ti.get("direction"),
                    "entry_zone": {"zone_low": ez.get("zone_low"),
                                   "zone_high": ez.get("zone_high"),
                                   "midpoint": ez.get("midpoint")},
                    "invalidation_level": inval,
                    "playbook": ti.get("playbook"),
                    "resolved": False,
                }
                fh.write(json.dumps(rec, default=str) + "\n")
                result["recorded"] += 1
                result["actions"].append(action_id)
        return result
    except Exception as exc:  # noqa: BLE001 — telemetry must never hurt a scan
        result["error"] = f"{type(exc).__name__}"
        return result


def load_open_actions(symbol: str, base_dir=None) -> list:
    open_path, _res, _met = _paths(symbol, base_dir)
    out = []
    if os.path.exists(open_path):
        with open(open_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def load_effect_metrics(symbol: str, base_dir=None) -> dict:
    """Read-back for the learning layer (policy evidence / future governance)."""
    _open, _res, met = _paths(symbol, base_dir)
    try:
        with open(met, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
