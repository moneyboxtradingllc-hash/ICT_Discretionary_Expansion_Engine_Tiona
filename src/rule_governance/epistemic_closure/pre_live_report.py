"""EPISTEMIC-CLOSURE-CERTIFICATION-1 §14 — the pre-live mechanics truth report.

ONE QUESTION:

    Could a competent trader understand what MECHANICS believes from this
    payload, without seeing the chart?

This is not Luna's prose and it is not a second opinion about the market. It is
what the organism would tell her, restated so a human can see whether the
picture is complete BEFORE a provider call is made and money is at risk.

It exists because the expensive failures of 2026 were not bad judgement. They
were missing context that nobody looked at first: a bot that launched at 10:31
and had never seen the open, a protected level that reported itself newborn on
every scan, a dealing range whose high was the level Luna was reasoning about
and whose low was her own objective -- computed, stored, and never shown.

DELIBERATELY NOT IN THE HOT PATH. Nothing imports this from production. It is a
preflight instrument, run by a human before the session.
"""
from __future__ import annotations

import glob
import json
import os

from rule_governance.epistemic_closure import capability_matrix
from rule_governance.epistemic_closure.fact_registry import by_id

#: repo root. The package sits at src/rule_governance/epistemic_closure/,
#: so four levels up. Derived rather than hardcoded so a future move
#: fails loudly at import instead of silently reading the wrong tree.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
_ARCHIVE = os.path.join(_ROOT, "data", "ai_brain")


def latest_payload():
    """The newest archived canonical snapshot, as a real Brain payload."""
    from ai_brain.brain_input import build_brain_input
    for day in sorted(
            {os.path.basename(p)[:8]
             for p in glob.glob(os.path.join(_ARCHIVE, "*_MNQ.json"))},
            reverse=True):
        for path in reversed(sorted(
                glob.glob(os.path.join(_ARCHIVE, f"{day}_*_MNQ.json")))):
            try:
                with open(path, encoding="utf-8") as fh:
                    snap = json.load(fh)["raw_snapshot"]
                return build_brain_input(snap, {}), os.path.basename(path)
            except Exception:  # noqa: BLE001
                continue
    return None, None


def _wrap(text, width):
    """Minimal word wrap. `textwrap` would do, but this report is read in a
    terminal beside other fixed-width output and keeping the rule local means
    the layout cannot drift with a library default."""
    words, line, out = str(text or "").split(), "", []
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out or [""]


def _age(now, then):
    try:
        from datetime import datetime
        delta = (datetime.fromisoformat(str(now))
                 - datetime.fromisoformat(str(then))).total_seconds() / 60
        return f"{delta:.0f}m"
    except Exception:  # noqa: BLE001
        return "?"


def render_payload_truth(payload=None, source=None) -> str:
    """What mechanics believes, in the order a trader would ask."""
    if payload is None:
        payload, source = latest_payload()
    if payload is None:
        return ("PRE-LIVE MECHANICS TRUTH\n\n  No archived canonical snapshot is "
                "available on this machine, so nothing can be shown. Absence of "
                "a report is not a clean report.")

    now = payload.get("timestamp")
    lines = [f"PRE-LIVE MECHANICS TRUTH   {now}",
             f"  source: {source}", ""]

    # ── what owns the tape ──────────────────────────────────────────────────
    ap = payload.get("active_path_state") or {}
    lines.append("ACTIVE PATH")
    if not ap.get("state_available", True):
        lines.append(f"  UNAVAILABLE — {ap.get('unavailable_reason')}")
    else:
        prog = ap.get("progression") or {}
        lines.append(f"  owner={ap.get('owner')}  status={ap.get('status')}  "
                     f"forming={ap.get('forming_direction')}")
        lines.append(f"  confirmed on {prog.get('supporting_timeframes')} "
                     f"(highest {prog.get('highest_confirmed')})")
        lb = ap.get("load_bearing_structure") or {}
        lines.append(f"  rests on {lb.get('level')} ({lb.get('timeframe')}) "
                     f"intact={lb.get('intact')}")
    lines.append("  SCOPE LIMIT: one ownership claim only. A counter-path "
                 "retracement and a true reversal look identical here.")
    lines.append("")

    # ── what is defended, and for how long ──────────────────────────────────
    lines.append("PROTECTED STRUCTURE (age is now trustworthy)")
    by_tf = (payload.get("protected_swings") or {}).get("by_timeframe") or {}
    any_level = False
    for side in ("highs", "lows"):
        for tf, rec in sorted((by_tf.get(side) or {}).items()):
            any_level = True
            lines.append(f"  {side[:-1]:>4} {tf:>4}  {rec.get('level')}  "
                         f"born {str(rec.get('registered_at'))[11:19]}  "
                         f"held {_age(now, rec.get('registered_at'))}  "
                         f"({rec.get('basis')})")
    if not any_level:
        lines.append("  none registered")
    lines.append("")

    # ── where liquidity is, and what we cannot say about it ─────────────────
    liq = payload.get("liquidity") or {}
    lines.append("LIQUIDITY")
    lines.append(f"  buy-side  {liq.get('nearest_buy_side')}"
                 f"      sell-side {liq.get('nearest_sell_side')}")
    lines.append("  READ WITH CARE: these are HIGHEST-TIMEFRAME-FIRST, not "
                 "mathematically nearest to price.")
    lines.append("  CANNOT SAY: when a pool formed, or whether this exact pool "
                 "is still untaken.")
    lines.append(f"  active draw: {liq.get('active_draw')}")
    lines.append("")

    # ── the auction ─────────────────────────────────────────────────────────
    dr = (payload.get("market") or {}).get("dealing_range") or {}
    lines.append("DEALING RANGE")
    if dr.get("high") is None:
        lines.append("  unavailable")
    else:
        pos = dr.get("position")
        lines.append(f"  {dr.get('low')} — {dr.get('high')}  "
                     f"mid {dr.get('midpoint')}  source {dr.get('source_tf')}")
        lines.append(f"  position {pos}  zone {dr.get('zone')!r}")
        if isinstance(pos, (int, float)) and not 0.0 <= pos <= 1.0:
            lines.append("  *** PRICE IS OUTSIDE THIS RANGE. The zone label is "
                         "UNSOUND — position is unclamped. ***")
        else:
            lines.append("  CONTAINMENT IS UNVERIFIED: no check establishes that "
                         "this range is still the operative one.")
    lines.append("")

    # ── can we even see the session? ────────────────────────────────────────
    lines.append("SESSION COMPLETENESS")
    lines.append("  Startup recovery is NOT wired into production. If this "
                 "process launched mid-session, structure that formed before it "
                 "started does not exist for it.")
    degraded = payload.get("degraded") or []
    lines.append(f"  degraded flags: {degraded if degraded else 'none'}")
    lines.append("")

    # ── the honest ledger of what is missing ────────────────────────────────
    blocked = capability_matrix.blocked()
    lines.append(f"KNOWN REPRESENTATION GAPS ({len(blocked)})")
    for cap in blocked:
        lines.append(f"  - {cap['question']}")
        # The gap verbatim, wrapped. Truncating it to a first sentence produced
        # lines like "NO. NO." and threw away the part that says who owns it.
        for chunk in _wrap(cap["gap"], 72):
            lines.append(f"      {chunk}")
    lines.append("")

    registry = by_id()
    legacy = [f for f, c in registry.items() if c["authority_class"] == "LEGACY"]
    lines.append(f"FIELDS THAT DO NOT MEAN WHAT THEY SAY ({len(legacy)})")
    for fid in sorted(legacy):
        lines.append(f"  - {fid}: {registry[fid]['semantic_claim']}")
    return "\n".join(lines)
