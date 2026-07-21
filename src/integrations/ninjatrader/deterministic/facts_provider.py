"""Mechanical facts provider — WIRED to the organism's real authorities on MNQ.

Builds the canonical snapshot from MNQ bars via the SAME deterministic mechanical
pipeline the organism uses (build_snapshot; the AI Brain is gated OFF by default,
so NO OpenAI is called), then extracts the 20 mechanical facts the deterministic
author needs from the REAL subsystems:

  * qualification / playbook / decision  -> direction + setup family
  * structure / liquidity / expansion    -> structural / liquidity / displacement evidence
  * narrative_authority                  -> protected-zone permit + invalidation level
  * market_commander (via execution_gate)-> environmental permit / STAND_DOWN
  * execution_gate                       -> trigger, regime, council, promoted-rule,
                                            narrative, commander permits
  * structural swing / protected swing   -> structural invalidation price fallback

The gate's BRAIN_AUTHORSHIP check is deliberately EXCLUDED: this lane is authored
by deterministic_sim_author (explicit predicates), never the AI Brain. FC-0B's
chase-cap intent is enforced by this lane's 20-pt structural stop cap.
"""
from __future__ import annotations

import sys
from typing import Optional

# Bullish/bearish -> long/short. Anything else (neutral/conflicted) -> unknown.
_BULL_BEAR = {"bullish": "long", "bearish": "short"}
_TFS = ("1m", "3m", "5m", "15m")


def _dir(x) -> Optional[str]:
    return _BULL_BEAR.get(str(x).lower())


def _any_tf(d: dict, key: str) -> bool:
    return any(bool((d.get(tf) or {}).get(key)) for tf in _TFS)


def build_mnq_snapshot(bars: list):
    """Run the real mechanical pipeline on MNQ 1m bars. Returns
    (snapshot, decision, gate). No OpenAI (Brain gated off by default)."""
    from data_feed.timeframe_builder import build_timeframes
    from market_data.snapshot_builder import build_snapshot
    from trade_intent.intent_builder import build_intent
    from decision_authority.decision_engine import make_decision
    from execution_gate.execution_gate import evaluate_gate

    tfs = build_timeframes(bars or [])
    snapshot = build_snapshot(tfs, symbol="MNQ SEP26")
    # Same sanctioned seam scan_loop uses — populates trade_intent.entry_zone,
    # the input to the real FC-0B verdict.
    snapshot["trade_intent"] = build_intent(snapshot, "MNQ SEP26")
    decision = make_decision(snapshot)
    gate = evaluate_gate(snapshot)
    # Hard invariant for this lane: the Brain must never have been invoked.
    if "openai" in sys.modules:
        raise RuntimeError("openai imported during deterministic MNQ scan — aborting")
    return snapshot, decision, gate


def _structural_invalidation(na: dict, structure: dict, direction: str,
                             entry: float) -> Optional[float]:
    """Structural invalidation price: narrative invalidation_level if present,
    else nearest protected swing / structure swing on the correct side."""
    lvl = na.get("invalidation_level")
    if isinstance(lvl, (int, float)) and lvl > 0:
        return float(lvl)
    if direction == "long":
        cands = [na.get("protected_low")] + \
                [(structure.get(tf) or {}).get("last_swing_low") for tf in _TFS]
        cands = [c for c in cands if isinstance(c, (int, float)) and c < entry]
        return max(cands) if cands else None      # nearest below entry
    if direction == "short":
        cands = [na.get("protected_high")] + \
                [(structure.get(tf) or {}).get("last_swing_high") for tf in _TFS]
        cands = [c for c in cands if isinstance(c, (int, float)) and c > entry]
        return min(cands) if cands else None      # nearest above entry
    return None


def build_facts_from_snapshot(snapshot: dict, decision: dict, gate: dict,
                              last_price: Optional[float]) -> dict:
    qual = snapshot.get("qualification", {}) or {}
    pb = snapshot.get("playbook", {}) or {}
    na = snapshot.get("narrative_authority", {}) or {}
    structure = snapshot.get("structure", {}) or {}
    liq = snapshot.get("liquidity", {}) or {}
    exp = snapshot.get("expansion", {}) or {}

    from paper_execution.order_builder import evaluate_fc0b, _preferred_candidate

    direction = _dir(decision.get("direction"))
    entry = last_price if isinstance(last_price, (int, float)) else None

    # Structural invalidation: the setup's REAL invalidation_level (price_level),
    # then narrative, then a protected/structure swing on the correct side.
    ti = snapshot.get("trade_intent", {}) or {}
    ez = ti.get("entry_zone") or {}
    pref_c = _preferred_candidate(snapshot)
    pl = (pref_c.get("price_level") or {}) if isinstance(pref_c, dict) else {}
    invalidation = pl.get("invalidation_level")
    if not isinstance(invalidation, (int, float)):
        invalidation = (_structural_invalidation(na, structure, direction, entry)
                        if (direction and entry) else None)

    commander_permits = bool(gate.get("commander_permits_trade", False))
    # The mechanical (non-Brain) gate: every sub-authority the execution gate
    # checks EXCEPT brain_authorship, which this deterministic lane replaces.
    mech_gate = all(bool(gate.get(k)) for k in (
        "trigger_requirement_met", "narrative_permits_trade", "commander_permits_trade",
        "council_permits_trade", "regime_permission_allowed", "no_promoted_rule_block"))

    setup_family = pb.get("selected_playbook")
    if setup_family in (None, "", "no_playbook"):
        setup_family = None

    # ── ACTUAL FC-0B verdict — the sanctioned order_builder.evaluate_fc0b seam.
    # Entry-location / chase authority, SEPARATE from the 20-pt structural stop
    # cap (which stays its own check in the risk engine). Indeterminable FC-0B
    # inputs -> None -> author fails closed (NO_TRADE).
    fc_relation = ez.get("price_relation")
    fc_entry = ez.get("current_price") if ez.get("current_price") is not None else entry
    fc_stop = pl.get("invalidation_level")
    if fc_stop is None:
        fc_stop = ez.get("zone_low") if direction == "long" else ez.get("zone_high")
    fc_mid = pl.get("midpoint") if pl.get("midpoint") is not None else ez.get("midpoint")
    if fc_relation is None or fc_entry is None or fc_stop is None:
        fc0b = None   # FC-0B indeterminable -> NO_TRADE upstream
    else:
        _fc_ok, _fc_reason = evaluate_fc0b("market", fc_relation, fc_entry, fc_stop, fc_mid)
        fc0b = bool(_fc_ok)

    return {
        "setup_family": setup_family,
        "direction": direction,
        "qualification_direction": _dir(qual.get("direction")),
        "playbook_direction": _dir(pb.get("direction")),
        "decision_direction": direction,
        "liquidity_evidence": bool(_any_tf(liq, "sweep_detected")),
        "structural_evidence": bool(_any_tf(structure, "bos") or _any_tf(structure, "mss")),
        "displacement_evidence": bool(_any_tf(exp, "displacement_detected")),
        "trigger_confirmed": bool(gate.get("trigger_requirement_met", False)),
        "protected_zone_permits": bool(gate.get("narrative_permits_trade", False)),
        # Commander verdict consumed ONLY through the sanctioned gate adapter
        # (commander_permits_trade), never the raw matrix.
        "commander_state": ("STAND_DOWN" if not commander_permits else "PROCEED"),
        # None when FC-0B is indeterminable -> author treats as unknown -> NO_TRADE.
        "fc0b_permits": (None if fc0b is None else bool(fc0b)),
        "entry_invalidation": invalidation,
        "opposing_direction": None,
        "final_gate_authorizes": bool(mech_gate),
        "expected_entry": entry,
        # Provenance.
        "_provenance": "WIRED: build_snapshot -> make_decision -> evaluate_gate "
                       "(brain_authorship excluded; deterministic authorship)",
        "_decision_state": decision.get("decision"),
        "_qual_status": qual.get("status"),
    }


def build_facts(bars: list, quote: dict) -> dict:
    """Convenience: build the snapshot and extract facts in one call."""
    snapshot, decision, gate = build_mnq_snapshot(bars)
    return build_facts_from_snapshot(snapshot, decision, gate,
                                     (quote or {}).get("last"))
