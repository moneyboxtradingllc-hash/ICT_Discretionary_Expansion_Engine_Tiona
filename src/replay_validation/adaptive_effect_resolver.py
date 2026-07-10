"""
ADAPT-LOOP-2 — Adaptive Effect Resolver (replay side, 2026-07-09).

Closes the second-order loop: joins the pipeline's recorded adaptive actions
(adaptive_learning.adaptive_effect open ledger) with COUNTERFACTUAL outcomes
scored by the SimBroker on the archived tape, then writes the resolved ledger
+ aggregate metrics the learning layer reads back.

Effect classification (counterfactual trade = live doctrine: zone-midpoint
limit, stop = invalidation else zone edge + 0.08, TP 2R, BE 1R, EOD flatten):

  soft_block       helped if counterfactual R < 0 (blocked a loser)
                   hurt   if counterfactual R > 0 (blocked a winner)
  size_reduce      effect_r = reduction_fraction × (−R): positive = saved risk
                   on a loser, negative = surrendered gain on a winner
  confidence_lower helped if the dampened setup lost, hurt if it won
  never_filled     expired (no counterfactual exists — counted, not judged)

The pipeline never imports this module; results flow back as data files.

CLI: python -m replay_validation.adaptive_effect_resolver --date 20260709
"""
import json
import os
from datetime import datetime, timezone

from adaptive_learning.adaptive_effect import load_open_actions, _paths
from replay_validation.candle_archive import load_session
from replay_validation.sim_broker import simulate_trade, stop_from_intent

_STOP_BUFFER = 0.08


def _counterfactual(tape: list, action: dict) -> "dict | None":
    ez = action.get("entry_zone") or {}
    mid = ez.get("midpoint")
    if mid is None and ez.get("zone_low") is not None:
        mid = round((float(ez["zone_low"]) + float(ez["zone_high"])) / 2, 3)
    stop = stop_from_intent(ez, action.get("direction") or "",
                            invalidation_level=action.get("invalidation_level"),
                            buffer=_STOP_BUFFER)
    if mid is None or stop is None:
        return None
    return simulate_trade(tape, action.get("timestamp"),
                          action.get("direction") or "", stop=stop,
                          entry_price=float(mid), target_r=2.0,
                          breakeven_r=1.0, max_bars=240)


def _classify(action: dict, trade: "dict | None") -> dict:
    if trade is None:
        return {"outcome": "expired", "effect_r": 0.0}
    r = float(trade["r"])
    t = action["action_type"]
    if t == "soft_block":
        outcome = "helped" if r < 0 else ("hurt" if r > 0 else "neutral")
        return {"outcome": outcome, "effect_r": round(-r, 3),
                "counterfactual_r": r}
    if t == "size_reduce":
        d = action.get("detail") or {}
        orig, final = d.get("original_qty"), d.get("final_qty")
        try:
            frac = max(0.0, 1.0 - float(final) / float(orig))
        except (TypeError, ValueError, ZeroDivisionError):
            frac = 0.0
        effect = round(frac * -r, 3)   # avoided share of a loss (+) / gain (−)
        outcome = "helped" if effect > 0 else ("hurt" if effect < 0 else "neutral")
        return {"outcome": outcome, "effect_r": effect, "counterfactual_r": r,
                "reduction_fraction": round(frac, 3)}
    # confidence_lower — informational grade against the setup's outcome
    outcome = "helped" if r < 0 else ("hurt" if r > 0 else "neutral")
    return {"outcome": outcome, "effect_r": 0.0, "counterfactual_r": r}


def resolve_effects(date: str, symbol: str = "QQQ", base_dir=None) -> dict:
    """Resolve every open action recorded on the given ET date."""
    open_path, res_path, met_path = _paths(symbol, base_dir)
    actions = [a for a in load_open_actions(symbol, base_dir)
               if not a.get("resolved")
               and str(a.get("timestamp", ""))[:10].replace("-", "") == date]
    if not actions:
        return {"date": date, "resolved": 0, "metrics": {}}
    tape = load_session(date, symbol)   # raises if the day was never archived

    resolved_ids, resolved_rows = set(), []
    if os.path.exists(res_path):
        with open(res_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    resolved_ids.add(json.loads(line).get("action_id"))
                except json.JSONDecodeError:
                    continue

    with open(res_path, "a", encoding="utf-8") as fh:
        for a in actions:
            if a["action_id"] in resolved_ids:
                continue
            trade = _counterfactual(tape, a)
            row = dict(a, resolved=True,
                       resolved_at=datetime.now(timezone.utc).isoformat(),
                       **_classify(a, trade))
            fh.write(json.dumps(row, default=str) + "\n")
            resolved_rows.append(row)

    metrics = _aggregate(res_path)
    with open(met_path, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=1)
    return {"date": date, "resolved": len(resolved_rows), "metrics": metrics}


def _aggregate(res_path: str) -> dict:
    by_type = {}
    if os.path.exists(res_path):
        with open(res_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = row.get("action_type")
                b = by_type.setdefault(t, {"n": 0, "helped": 0, "hurt": 0,
                                           "neutral": 0, "expired": 0,
                                           "net_effect_r": 0.0})
                b["n"] += 1
                b[row.get("outcome", "neutral")] = b.get(row.get("outcome", "neutral"), 0) + 1
                b["net_effect_r"] = round(b["net_effect_r"] + float(row.get("effect_r") or 0.0), 3)
    return {"updated_at": datetime.now(timezone.utc).isoformat(),
            "by_action_type": by_type}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="ADAPT-LOOP-2 effect resolver")
    p.add_argument("--date", required=True)
    p.add_argument("--symbol", default="QQQ")
    a = p.parse_args()
    out = resolve_effects(a.date, a.symbol)
    print(json.dumps(out, indent=1, default=str))
